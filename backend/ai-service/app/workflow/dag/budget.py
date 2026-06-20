"""Phase 9 DAG 引擎 — 预算追踪器。

做什么：注入到 DAG 引擎运行时，每次工具调用时实时上报预算消耗。
为什么这样做：防止单个 State 或整个 Plan 的工具调用失控。
"""

from __future__ import annotations

from app.logger import logger
from app.workflow.dag.types import GlobalBudget, StateBudget


class BudgetTracker:
    """预算追踪器。

    做什么：注入到 DAG 引擎运行时，每次工具调用时实时上报。
    为什么这样做：防止单个 State 或整个 Plan 的工具调用失控。
    """

    def __init__(
        self,
        state_budget: StateBudget,
        global_budget: GlobalBudget,
        trace_id: str = "",
    ):
        """初始化预算追踪器。

        参数:
            state_budget: State 级别预算配置。
            global_budget: Plan 级别全局预算配置。
            trace_id: 追踪 ID，用于日志。
        """
        self.state_limit = state_budget.max_tool_calls
        self.global_limit = global_budget.max_total_tool_calls
        self.state_consumed = 0
        self.global_consumed = 0
        self.trace_id = trace_id

    def consume_tool_call(self) -> bool:
        """消耗一次工具调用配额。

        做什么：每次工具调用时调用，检查是否超出预算。
        返回:
            True 表示预算充足，False 表示预算已耗尽。
        """
        self.state_consumed += 1
        self.global_consumed += 1

        if self.state_consumed > self.state_limit:
            logger.warning(
                f"[TraceID:{self.trace_id}] State 级预算耗尽: "
                f"consumed={self.state_consumed}, limit={self.state_limit}"
            )
            return False

        if self.global_consumed > self.global_limit:
            logger.warning(
                f"[TraceID:{self.trace_id}] Plan 级预算耗尽: "
                f"consumed={self.global_consumed}, limit={self.global_limit}"
            )
            return False

        return True

    def reset_state_budget(self) -> None:
        """State 切换时重置 State 级计数器。"""
        self.state_consumed = 0

    def is_state_budget_exhausted(self) -> bool:
        """检查 State 级预算是否耗尽。"""
        return self.state_consumed >= self.state_limit

    def is_global_budget_exhausted(self) -> bool:
        """检查 Plan 级预算是否耗尽。"""
        return self.global_consumed >= self.global_limit

    def get_consumption_summary(self) -> dict[str, int]:
        """获取当前预算消耗摘要。"""
        return {
            "state_consumed": self.state_consumed,
            "state_limit": self.state_limit,
            "global_consumed": self.global_consumed,
            "global_limit": self.global_limit,
        }
