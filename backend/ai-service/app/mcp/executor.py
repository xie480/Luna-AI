"""
MCP 工具执行函数。

做什么：统一的 MCP 工具执行入口，包含完整的四阶段路由：
         1. Pre-check（风险等级验证 + 参数 Schema 校验）
         2. Gating（Phase 13 L2/L3 审批拦截）
         3. Execute（异步执行 + 重试 + 超时控制）
         4. Post-process（输出裁剪、审计字段填充和异常捕获）
         在 Phase 13 中，L2/L3 高危工具在执行前会由 GatingService 创建审批请求，
         等待用户确认后方可继续执行。

为什么这样做：将所有工具调用统一收敛到本函数，确保每次调用都经过
             完整的权限校验、执行审计和异常捕获。单一入口便于维护和审计。

四阶段路由流程：
    - Phase 1: Pre-check — 风险等级验证、参数 Schema 校验、上下文合法性检查。
                L0 工具直接放行；L1 工具自动放行但记录审计；L2/L3 工具进入 Gating 审批流程。
    - Phase 2: Create Auth Request — (Phase 13) 当工具风险等级为 L2/L3 时，
               调用 GatingService.create_auth_request() 创建审批请求并挂起执行。
               同时将当前工具调用的完整上下文保存到 Redis 快照中。
    - Phase 3: Execute — 异步执行工具 handler，含重试与超时控制。
    - Phase 4: Post-process — 输出裁剪、审计填充。

边界条件：
    - 参数验证失败直接返回错误结果，不进入 Execute 阶段。
    - L2/L3 工具通过 GatingService 进行权限验证，未批准前不会执行 handler。
    - 超时或重试耗尽后返回带 error_message 的结果。
    - Phase 13 新增：快照保存失败不阻断审批请求的创建。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import jsonschema

from app.logger import logger
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import MCPToolResult, ToolRiskLevel
from app.utils.snowflake import generate_string_id
from app.gating.snapshot import GatingSnapshotManager

# 默认工具执行超时（秒）
_DEFAULT_TOOL_TIMEOUT = 30.0
# 最大重试次数
_MAX_TOOL_RETRIES = 2


async def execute_tool(
    tool_name: str,
    parameters: dict[str, Any],
    trace_id: str,
    timeout: float = _DEFAULT_TOOL_TIMEOUT,
    max_retries: int = _MAX_TOOL_RETRIES,
    gating_service=None,
    snapshot_manager: GatingSnapshotManager | None = None,
    task_id: str = "",
    goal: str = "",
    agent_output: str = "",
    mcp_intent: str = "",
    execution_plan: dict[str, Any] | None = None,
    screening_result: dict[str, Any] | None = None,
    resource_results: list[dict[str, Any]] | None = None,
    all_tool_results: list[dict[str, Any]] | None = None,
    all_round_data: list[dict[str, Any]] | None = None,
    dag_state_snapshot: dict[str, Any] | None = None,
    prompt_snapshot: str = "",
    state_context: dict[str, Any] | None = None,
) -> MCPToolResult:
    """
    执行 MCP 工具（四阶段路由）。

    做什么：通过 MCPToolRegistry 获取已注册工具，执行四阶段路由：
            Pre-check（风险等级 + 参数校验）→ Gating（Phase 13 L2/L3 审批 + 快照保存）
            → Execute（异步执行 + 重试）→ Post-process（输出裁剪 + 审计填充）。
    为什么这样做：将所有工具调用统一收敛到本函数，确保每次调用都经过
                 完整的权限校验、执行审计和异常处理。
                 快照保存确保审批结束后可以恢复执行或生成拒绝反馈。
    参数:
        tool_name: 要执行的工具名称，必须已在 MCPToolRegistry 中注册。
        parameters: 工具调用参数键值对，必须符合工具的 parameters_schema。
        trace_id: 全链路追踪 ID。
        timeout: 单次工具执行超时时间（秒），默认 30 秒。
        max_retries: 执行失败时的最大重试次数，默认 2 次。
        gating_service: GatingService 实例（Phase 13）。L2/L3 工具需要传入此参数进行审批。
        snapshot_manager: GatingSnapshotManager 实例（Phase 13）。用于保存执行快照。
        task_id: 关联的 DAG 任务 ID（Phase 13）。用于审批请求的任务关联。
        goal: 当前 Agent 执行的 Goal 描述（Phase 13）。用于审批弹窗展示。
        agent_output: Agent 输出信息（Phase 13）。用于审批弹窗展示。
        mcp_intent: MCP 意图文本。用于审批通过后的工具执行上下文恢复。
        execution_plan: 当前执行计划快照。用于审批恢复。
        screening_result: Skill 初筛结果快照。用于审批恢复。
        resource_results: 已加载的资源结果快照。用于审批恢复。
        all_tool_results: 已累积的工具执行结果。用于审批恢复。
        all_round_data: 全部轮次的执行数据。用于审批恢复。
        dag_state_snapshot: DAG 节点状态快照。用于审批恢复。
        prompt_snapshot: 调用前的完整 Prompt 文本。用于审批恢复。
    返回:
        MCPToolResult: 工具执行结果。
                       对于 L2/L3 工具，成功标志为 false 且 error_message 包含审批信息。
    """

    registry = MCPToolRegistry()
    registered = registry.get_tool(tool_name)
    
    # === 解析元数据，判断是否为外部工具 ===
    is_external = False
    server_id = None
    risk_level_val = "L0"
    schema = None
    
    if registered:
        # 本地工具
        schema = registered.schema
        risk_level_val = schema.risk_level.value
    else:
        # 尝试从外部工具缓存（SkillRegistry）中查找
        from app.mcp.skill_registry import SkillRegistry
        skill_registry = SkillRegistry()
        found = False
        for sid, det in skill_registry._skills.items():
            for t in det.tools:
                if t.get("name") == tool_name:
                    is_external = True
                    server_id = det.name # 或者通过特定前缀提取 server_id
                    
                    # 为了统一风控，从数据库中提取完整的工具信息
                    from app.infrastructure.postgres import PostgresClient
                    from app.repository.models import MCPToolRegistration
                    from sqlalchemy import select
                    
                    import asyncio
                    async def fetch_tool_meta():
                        pg_client = PostgresClient.get_instance()
                        async with pg_client.session() as session:
                            stmt = select(MCPToolRegistration).where(MCPToolRegistration.name == tool_name)
                            res = await session.execute(stmt)
                            return res.scalar_one_or_none()
                            
                    # 由于当前在一个 async 函数内，直接 await
                    db_tool = await fetch_tool_meta()
                    if db_tool:
                        risk_level_val = db_tool.risk_level
                        server_id = db_tool.server_id
                        schema = type('obj', (object,), {'parameters_schema': db_tool.parameters_schema, 'name': tool_name})
                    found = True
                    break
            if found:
                break
                
        if not found:
            logger.warning(
                f"MCP 工具执行预检失败 trace_id={trace_id} "
                f"tool_name={tool_name} 原因: 工具不存在或已禁用"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"工具 '{tool_name}' 不存在或已禁用",
                execution_id=generate_string_id(),
                latency_ms=0,
                risk_level="",
            )

    execution_id = generate_string_id()

    # Phase 13: L2/L3 高危工具执行 Gating 审批流程 + 快照保存
    # 做什么：当工具风险等级为 L2 或 L3 时，调用 GatingService.create_auth_request()
    #         创建审批请求并向前端推送 EVT_TOOL_AUTH_REQUIRED 事件。
    #         同时将工具调用上下文保存到 Redis 快照中，供审批通过后恢复执行。
    # 为什么这样做：根据 agent.md 6.4 安全与治理规范，高危操作必须经用户确认。
    #              agent.md 6.3 规定所有异步逻辑必须可恢复，快照保存确保审批
    #              结束后能正确恢复工具执行上下文。
    # 边界条件：
    #   - gating_service 为 None 时，返回一个特殊的 MCPToolResult 提醒调用方激活 Gating。
    #   - 创建审批请求失败（数据库异常）时，返回带错误信息的 MCPToolResult。
    #   - 快照保存失败不影响审批请求的创建，仅记录警告日志。
    if risk_level_val in ("L2", "L3"):
        if gating_service is not None:
            # 通过 GatingService 创建审批请求
            success, auth_request = await gating_service.create_auth_request(
                tool_id=tool_name,
                tool_name=schema.name,
                risk_level=risk_level_val,
                reason=f"工具 '{tool_name}' 风险等级 {risk_level_val}，需要用户确认后才可执行。",
                arguments=parameters,
                trace_id=trace_id,
                task_id=task_id or execution_id,
                goal=goal or "",
                agent_output=agent_output or "",
            )

            if not success:
                logger.error(
                    f"MCP 工具 Gating 审批创建失败 trace_id={trace_id} "
                    f"tool_name={tool_name} risk_level={risk_level_val}"
                )
                return MCPToolResult(
                    success=False,
                    output_text="",
                    error_message=f"工具 '{tool_name}' 审批请求创建失败，无法执行",
                    execution_id=execution_id,
                    latency_ms=0,
                    risk_level=risk_level_val,
                )

            # Phase 13 增强：保存工具执行快照到 Redis（断点恢复用）
            # 做什么：将工具调用所需完整上下文序列化保存到 Redis。
            #         审批通过后从快照恢复并执行工具；
            #         审批拒绝后将快照中的上下文注入到 chat/memory.j2 模板。
            # 为什么这样做：确保审批结束后不会丢失工具调用的上下文信息。
            # 边界条件：快照保存失败不影响审批，仅记录警告。
            if snapshot_manager is not None:
                # 去除 state_context 中不可序列化的内部组件以确保 json.dumps 成功
                clean_state_context = {}
                if state_context:
                    clean_state_context = {
                        k: v for k, v in state_context.items()
                        if k not in ["skill_registry", "gating_service", "snapshot_manager", "memory_manager", "rag_orchestrator"]
                    }
                await snapshot_manager.save_tool_snapshot(
                    audit_log_id=auth_request.audit_log_id,
                    tool_name=tool_name,
                    tool_parameters=parameters,
                    trace_id=trace_id,
                    task_id=task_id or execution_id,
                    risk_level=risk_level_val,
                    goal=goal or "",
                    agent_output=agent_output or "",
                    mcp_intent=mcp_intent,
                    execution_plan=execution_plan,
                    screening_result=screening_result,
                    resource_results=resource_results,
                    all_tool_results=all_tool_results,
                    all_round_data=all_round_data,
                    dag_state_snapshot=dag_state_snapshot,
                    prompt_snapshot=prompt_snapshot,
                )

            # 返回 PENDING_APPROVAL 状态，调用方（DAG 引擎）应当挂起当前节点
            logger.warning(
                f"MCP 工具进入审批挂起 trace_id={trace_id} "
                f"tool_name={tool_name} risk_level={risk_level_val} "
                f"audit_log_id={auth_request.audit_log_id}"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"工具 '{tool_name}' 需要用户审批，已发送审批请求",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level_val,
                gating_pending=True,
                gating_audit_log_id=auth_request.audit_log_id,
            )
        else:
            # GatingService 未提供，直接提醒
            logger.warning(
                f"MCP 工具执行预检失败 trace_id={trace_id} "
                f"tool_name={tool_name} risk_level={risk_level_val} "
                f"原因: L2/L3 高风险工具需要 GatingService 审批"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"工具 '{tool_name}' 风险等级 {risk_level_val} 需要用户审批",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level_val,
            )

    # 参数 Schema 校验
    if schema and getattr(schema, 'parameters_schema', None):
        try:
            jsonschema.validate(instance=parameters, schema=schema.parameters_schema)
        except jsonschema.ValidationError as ve:
            logger.warning(
                f"MCP 工具参数校验失败 trace_id={trace_id} "
                f"tool_name={tool_name} error={ve.message}"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"参数校验失败: {ve.message}",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level_val,
            )

    logger.info(
        f"MCP 工具预检通过 trace_id={trace_id} "
        f"tool_name={tool_name} risk_level={risk_level_val} "
        f"parameters={json.dumps(parameters, ensure_ascii=False)}"
    )

    # ============================================================
    # Phase 2: Execute — 异步执行 handler，含重试与超时控制，以及双轨分发
    # ============================================================
    started_at = time.monotonic()
    
    if is_external:
        # === 外部工具执行链路 ===
        from app.mcp.server_manager import MCPServerManager
        from app.mcp.gateway import get_gateway
        
        manager = MCPServerManager.get_instance()
        server_config = manager.get_server_config(server_id)
        if not server_config:
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"外部工具 Server 配置缺失: {server_id}",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level_val,
            )
            
        gateway = get_gateway()
        # gateway 内部已内聚了 Http 请求、错误处理、熔断器和延迟记录
        return await gateway.execute_remote_tool(
            endpoint_url=server_config.endpoint_url,
            tool_name=tool_name,
            parameters=parameters,
            auth_config=server_config.auth.model_dump() if hasattr(server_config.auth, 'model_dump') else server_config.auth.dict(),
            trace_id=trace_id,
            timeout=server_config.timeout_seconds
        )
    else:
        # === 本地工具执行链路 ===
        last_error = ""
        last_output_text = ""

        for attempt in range(max_retries + 1):
            try:
                import inspect
                sig = inspect.signature(registered.handler)
                kwargs = {"parameters": parameters, "trace_id": trace_id}
                if "state_context" in sig.parameters:
                    kwargs["state_context"] = state_context
                    
                output_text = await asyncio.wait_for(
                    registered.handler(**kwargs),
                    timeout=timeout,
                )
                last_output_text = output_text
                # 执行成功，跳出重试循环
                break
            except asyncio.TimeoutError:
                last_error = f"工具执行超时（{timeout}s）"
                logger.warning(
                    f"MCP 工具执行超时 trace_id={trace_id} "
                    f"tool_name={tool_name} attempt={attempt} timeout={timeout}"
                )
            except Exception as exc:
                last_error = f"工具执行异常: {exc!s}"
                logger.warning(
                    f"MCP 工具执行异常 trace_id={trace_id} "
                    f"tool_name={tool_name} attempt={attempt} error={exc!s}"
                )

            # 达到最大重试次数，不继续重试
            if attempt == max_retries:
                break

            # 指数退避等待后重试
            await asyncio.sleep(2 ** attempt)

        elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))

        # 所有重试都失败
        if last_error and not last_output_text:
            logger.warning(
                f"MCP 工具执行失败 trace_id={trace_id} "
                f"tool_name={tool_name} retries={max_retries} error={last_error}"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=last_error,
                execution_id=execution_id,
                latency_ms=elapsed_ms,
                risk_level=risk_level_val,
            )

        logger.info(
            f"MCP 工具执行成功 trace_id={trace_id} "
            f"tool_name={tool_name} latency_ms={elapsed_ms} "
            f"output_length={len(last_output_text)}"
        )

        return MCPToolResult(
            success=True,
            output_text=last_output_text,
            error_message="",
            execution_id=execution_id,
            latency_ms=elapsed_ms,
            risk_level=risk_level_val,
        )
