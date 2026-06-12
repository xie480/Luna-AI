"""
MCP Skill 最终失败处理。

做什么：当 Skill 三阶段执行达到最大步长或确认无法实现目标时，
        提取失败理由，供工作流节点处理后跳至主 Chat LLM 节点。
为什么这样做：避免系统在无法完成任务的情况下无限循环或死循环，
            确保用户能及时得到反馈。
边界条件：
    - 最大执行步长通过 settings.skill_max_execution_steps 配置，默认 30 步。
    - 最大退回次数通过 settings.skill_max_fallback_count 配置，默认 2 次。
    - 最终失败时部分结果包含已成功执行的部分。
"""

from __future__ import annotations

from typing import Any

from app.config.settings import settings
from app.mcp.skill_types import FinalFailState, ToolExecutionResult

# 最大执行步长（从 .env 配置读取）
_MAX_EXECUTION_STEPS: int = settings.skill_max_execution_steps

# 最大退回次数（从 .env 配置读取）
_MAX_FALLBACK_COUNT: int = settings.skill_max_fallback_count


def should_trigger_final_fail(
    step_count: int,
    fallback_count: int,
    tool_results: list[dict[str, Any]] | None = None,
    execution_plan: dict[str, Any] | None = None,  # noqa: ARG001
) -> FinalFailState | None:
    """判断是否触发最终失败。

    做什么：检查是否达到最大步长或最大退回次数。
    参数:
        step_count: 当前已执行步数。
        fallback_count: 当前已退回次数。
        tool_results: 已执行成功的工具结果列表。
        execution_plan: 当前执行计划（可能为空）。
    返回:
        FinalFailState 或 None（不需要触发时）。
    """
    if step_count >= _MAX_EXECUTION_STEPS:
        return FinalFailState(
            failure_reason=f"达到最大执行步长（{_MAX_EXECUTION_STEPS} 步），"
                          f"但任务尚未完成。已执行的步骤结果如下。",
            partial_results=[_tool_result_to_model(r) for r in (tool_results or [])],
            step_count_used=step_count,
            max_steps_reached=True,
        )

    if fallback_count >= _MAX_FALLBACK_COUNT:
        return FinalFailState(
            failure_reason=f"达到最大退回次数（{_MAX_FALLBACK_COUNT} 次），"
                          f"未能找到合适的技能完成任务。已执行的步骤结果如下。",
            partial_results=[_tool_result_to_model(r) for r in (tool_results or [])],
            step_count_used=step_count,
            max_steps_reached=False,
        )

    return None


def _tool_result_to_model(result: dict[str, Any]) -> ToolExecutionResult:
    """将工具结果字典转换为 ToolExecutionResult 模型。"""
    return ToolExecutionResult(
        tool_name=result.get("tool_name", "unknown"),
        success=result.get("success", False),
        output_text=result.get("output_text", ""),
        error_message=result.get("error_message", ""),
        resource_context_injected=result.get("resource_context_injected", []),
        latency_ms=result.get("latency_ms", 0),
    )
