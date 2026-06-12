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
    - v3.0：步长超限时触发重试（退回）而非直接失败，
            仅当超过最大退回次数时才触发最终失败。
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
    execution_plan: dict[str, Any] | None = None,
) -> FinalFailState | None:
    """判断是否触发最终失败。

    做什么：检查是否达到最大退回次数。
            v3.0 变更：步长超限不再直接触发最终失败，
            而是通过退回机制重试。只有当退回次数超过上限时才触发最终失败。
            因为步长超限说明技能选择或执行计划有问题，应当重新选择技能，
            而非直接放弃整个任务。
    参数:
        step_count: 当前已执行步数。
        fallback_count: 当前已退回次数。
        tool_results: 已执行成功的工具结果列表。
        execution_plan: 当前执行计划（可能为空）。
    返回:
        FinalFailState 或 None（不需要触发时）。
    """
    # v3.0：步长超限触发退回重试，不直接触发最终失败
    # 仅当退回次数超过上限时才触发最终失败
    if fallback_count >= _MAX_FALLBACK_COUNT:
        return FinalFailState(
            failure_reason=f"达到最大退回次数（{_MAX_FALLBACK_COUNT} 次），"
                          f"已执行 {step_count} 步，但未能找到合适的技能完成任务。"
                          f"以下是已执行的步骤结果。",
            partial_results=[_tool_result_to_model(r) for r in (tool_results or [])],
            step_count_used=step_count,
            max_steps_reached=False,
        )

    return None


def is_step_count_exceeded(step_count: int) -> bool:
    """判断是否达到最大步长限制（用于触发退回而非直接失败）。

    做什么：当当前累积步数超过最大步长时返回 True，
            触发上层调用方执行退回操作。
    v3.0 设计：步长超限 → 退回重试（更换技能/重新规划），而非直接失败。
    返回:
        bool: True 表示步数超限，需要触发退回。
    """
    return step_count >= _MAX_EXECUTION_STEPS


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
