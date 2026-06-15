"""
MCP 工具执行网关。

做什么：提供 MCP 工具调用的三阶段路由执行（Pre-check → Execute → Post-process）。
        作为副作用操作的唯一入口，所有工具调用必须经过此网关。
        网关负责：风险等级验证、参数 Schema 校验、异步执行 handler、
                 输出裁剪、审计字段填充和异常捕获。
        在 Phase 13 中，L2/L3 高危工具在执行前会由 GatingService 创建审批请求，
        等待用户确认后方可继续执行。
为什么这样做：Phase 12 要求工具不能由模型直调，必须经过 Python 控制面。
             本网关作为 Python 控制面的执行层，确保每次工具调用都有完整的
             执行记录、耗时统计和错误处理。
三阶段路由协议：
    - Phase 1: Pre-check — 风险等级验证、参数 Schema 校验、上下文合法性检查。
                L0 工具直接放行；L1 工具自动放行但记录审计；L2/L3 工具进入 Gating 审批流程。
    - Phase 2: Create Auth Request — (Phase 13) 当工具风险等级为 L2/L3 时，
                调用 GatingService.create_auth_request() 创建审批请求并挂起执行。
    - Phase 3: Execute — 异步执行工具 handler，含重试与超时控制。
                默认超时 30s，最大重试 2 次。
    - Phase 4: Post-process — 审计字段填充（execution_id、latency_ms）。
边界条件：
    - 仅限已注册到 MCPToolRegistry 的工具可执行。
    - 参数验证失败直接返回错误结果，不进入 Execute 阶段。
    - L2/L3 工具通过 GatingService 进行权限验证，未批准前不会执行 handler。
    - 超时或重试耗尽后返回带 error_message 的结果。
    - 所有异常由本网关捕获并序列化为 MCPToolResult，禁止向调用方传播异常。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import jsonschema

# ============================================================
# 常量定义
# ============================================================
from app.config.settings import settings
from app.logger import logger
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import MCPToolResult, ToolRiskLevel
from app.utils.snowflake import generate_string_id

# 默认工具执行超时时间（秒，从 .env 配置读取）
_DEFAULT_TOOL_TIMEOUT: float = settings.mcp_tool_timeout

# 工具执行最大重试次数（从 .env 配置读取）
_MAX_TOOL_RETRIES: int = settings.mcp_tool_max_retries


# ============================================================
# 核心执行函数
# ============================================================


async def execute_tool(
    tool_name: str,
    parameters: dict[str, Any],
    trace_id: str,
    timeout: float = _DEFAULT_TOOL_TIMEOUT,
    max_retries: int = _MAX_TOOL_RETRIES,
    gating_service=None,
    task_id: str = "",
    goal: str = "",
    agent_output: str = "",
) -> MCPToolResult:
    """
    执行 MCP 工具（四阶段路由）。

    做什么：通过 MCPToolRegistry 获取已注册工具，执行四阶段路由：
            Pre-check（风险等级 + 参数校验）→ Gating（Phase 13 L2/L3 审批）
            → Execute（异步执行 + 重试）→ Post-process（输出裁剪 + 审计填充）。
    为什么这样做：将所有工具调用统一收敛到本函数，确保每次调用都经过
                 完整的权限校验、执行审计和异常处理。
    参数:
        tool_name: 要执行的工具名称，必须已在 MCPToolRegistry 中注册。
        parameters: 工具调用参数键值对，必须符合工具的 parameters_schema。
        trace_id: 全链路追踪 ID。
        timeout: 单次工具执行超时时间（秒），默认 30 秒。
        max_retries: 执行失败时的最大重试次数，默认 2 次。
        gating_service: GatingService 实例（Phase 13）。L2/L3 工具需要传入此参数进行审批。
        task_id: 关联的 DAG 任务 ID（Phase 13）。用于审批请求的任务关联。
        goal: 当前 Agent 执行的 Goal 描述（Phase 13）。用于审批弹窗展示。
        agent_output: Agent 输出信息（Phase 13）。用于审批弹窗展示。
    返回:
        MCPToolResult: 工具执行结果。
                       对于 L2/L3 工具，成功标志为 false 且 error_message 包含审批信息。
    """

    registry = MCPToolRegistry()
    registered = registry.get_tool(tool_name)

    # ============================================================
    # Phase 1: Pre-check — 风险等级验证与参数 Schema 校验
    # ============================================================
    if registered is None:
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

    schema = registered.schema
    risk_level = schema.risk_level
    execution_id = generate_string_id()

    # Phase 13: L2/L3 高危工具执行 Gating 审批流程
    # 做什么：当工具风险等级为 L2 或 L3 时，调用 GatingService.create_auth_request()
    #         创建审批请求并向前端推送 EVT_TOOL_AUTH_REQUIRED 事件。
    #         调用方（DAG 引擎）根据返回结果决定是否挂起等待用户审批。
    # 为什么这样做：根据 agent.md 6.4 安全与治理规范，高危操作必须经用户确认。
    #              gating_service 参数由调用方传入，如果未提供则直接返回审批提醒。
    # 边界条件：
    #   - gating_service 为 None 时，返回一个特殊的 MCPToolResult 提醒调用方激活 Gating。
    #   - 创建审批请求失败（数据库异常）时，返回带错误信息的 MCPToolResult。
    if risk_level.value in (ToolRiskLevel.L2.value, ToolRiskLevel.L3.value):
        if gating_service is not None:
            # 通过 GatingService 创建审批请求
            success, auth_request = await gating_service.create_auth_request(
                tool_id=tool_name,
                tool_name=schema.name,
                risk_level=risk_level.value,
                reason=f"工具 '{tool_name}' 风险等级 {risk_level.value}，需要用户确认后才可执行。",
                arguments=parameters,
                trace_id=trace_id,
                task_id=task_id or execution_id,
                goal=goal or "",
                agent_output=agent_output or "",
            )

            if not success:
                logger.error(
                    f"MCP 工具 Gating 审批创建失败 trace_id={trace_id} "
                    f"tool_name={tool_name} risk_level={risk_level.value}"
                )
                return MCPToolResult(
                    success=False,
                    output_text="",
                    error_message=f"工具 '{tool_name}' 审批请求创建失败，无法执行",
                    execution_id=execution_id,
                    latency_ms=0,
                    risk_level=risk_level.value,
                )

            # 返回 PENDING_APPROVAL 状态，调用方（DAG 引擎）应当挂起当前节点
            logger.warning(
                f"MCP 工具进入审批挂起 trace_id={trace_id} "
                f"tool_name={tool_name} risk_level={risk_level.value} "
                f"audit_log_id={auth_request.audit_log_id}"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"工具 '{tool_name}' 需要用户审批，已发送审批请求",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level.value,
            )
        else:
            # GatingService 未提供，直接提醒
            logger.warning(
                f"MCP 工具执行预检失败 trace_id={trace_id} "
                f"tool_name={tool_name} risk_level={risk_level.value} "
                f"原因: L2/L3 高风险工具需要 GatingService 审批"
            )
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"工具 '{tool_name}' 风险等级 {risk_level.value} 需要用户审批",
                execution_id=execution_id,
                latency_ms=0,
                risk_level=risk_level.value,
            )

    # 参数 Schema 校验
    if schema.parameters_schema:
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
                risk_level=risk_level.value,
            )

    logger.info(
        f"MCP 工具预检通过 trace_id={trace_id} "
        f"tool_name={tool_name} risk_level={risk_level.value} "
        f"parameters={json.dumps(parameters, ensure_ascii=False)}"
    )

    # ============================================================
    # Phase 2: Execute — 异步执行 handler，含重试与超时控制
    # ============================================================
    started_at = time.monotonic()
    last_error = ""
    last_output_text = ""

    for attempt in range(max_retries + 1):
        try:
            output_text = await asyncio.wait_for(
                registered.handler(parameters=parameters, trace_id=trace_id),
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
            risk_level=risk_level.value,
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
        risk_level=risk_level.value,
    )
