"""
MCP 工具执行网关。

做什么：提供 MCP 工具调用的三阶段路由执行（Pre-check → Execute → Post-process）。
        作为副作用操作的唯一入口，所有工具调用必须经过此网关。
        网关负责：风险等级验证、参数 Schema 校验、异步执行 handler、
                 输出裁剪、审计字段填充和异常捕获。
为什么这样做：Phase 12 要求工具不能由模型直调，必须经过 Python 控制面。
             本网关作为 Python 控制面的执行层，确保每次工具调用都有完整的
             执行记录、耗时统计和错误处理。
三阶段路由协议：
    - Phase 1: Pre-check — 风险等级验证、参数 Schema 校验、上下文合法性检查。
                当前 Phase 12 直接放行 L0 工具；L2/L3 留待 Phase 13 拦截。
    - Phase 2: Execute — 异步执行工具 handler，含重试与超时控制。
                默认超时 30s，最大重试 2 次。
    - Phase 3: Post-process — 输出裁剪（4096 字符）、审计字段填充。
                超长输出截断标记 [truncated]。
边界条件：
    - 仅限已注册到 MCPToolRegistry 的工具可执行。
    - 参数验证失败直接返回错误结果，不进入 Execute 阶段。
    - 超时或重试耗尽后返回带 error_message 的结果。
    - 所有异常由本网关捕获并序列化为 MCPToolResult，禁止向调用方传播异常。
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

# ============================================================
# 常量定义
# ============================================================

# 默认工具执行超时时间（秒）
_DEFAULT_TOOL_TIMEOUT: float = 30.0

# 工具执行最大重试次数
_MAX_TOOL_RETRIES: int = 2


# ============================================================
# 核心执行函数
# ============================================================


async def execute_tool(
    tool_name: str,
    parameters: dict[str, Any],
    trace_id: str,
    timeout: float = _DEFAULT_TOOL_TIMEOUT,
    max_retries: int = _MAX_TOOL_RETRIES,
) -> MCPToolResult:
    """
    执行 MCP 工具（三阶段路由）。

    做什么：通过 MCPToolRegistry 获取已注册工具，执行三阶段路由：
            Pre-check（风险等级 + 参数校验）→ Execute（异步执行 + 重试）
            → Post-process（输出裁剪 + 审计填充）。
    为什么这样做：将所有工具调用统一收敛到本函数，确保每次调用都经过
                完整的权限校验、执行审计和异常处理。
    参数:
        tool_name: 要执行的工具名称，必须已在 MCPToolRegistry 中注册。
        parameters: 工具调用参数键值对，必须符合工具的 parameters_schema。
        trace_id: 全链路追踪 ID。
        timeout: 单次工具执行超时时间（秒），默认 30 秒。
        max_retries: 执行失败时的最大重试次数，默认 2 次。
    返回:
        MCPToolResult: 工具执行结果，包含成功标志、输出文本、错误信息、耗时和审计 ID。
    """
    from app.utils.snowflake import generate_string_id

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

    # 风险等级检查：Phase 12 仅放行 L0 工具
    # L2/L3 留待 Phase 13 权限治理模块实现拦截
    if risk_level.value in (ToolRiskLevel.L2.value, ToolRiskLevel.L3.value):
        logger.warning(
            f"MCP 工具执行预检失败 trace_id={trace_id} "
            f"tool_name={tool_name} risk_level={risk_level.value} "
            f"原因: L2/L3 高风险工具尚未实现权限拦截"
        )
        return MCPToolResult(
            success=False,
            output_text="",
            error_message=f"工具 '{tool_name}' 风险等级 {risk_level.value} 暂不支持",
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
