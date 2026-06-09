"""会话上下文装载节点。"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.llm.context_manager import count_tokens
from app.workflow.constants import (
    CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED,
    CHAT_WORKFLOW_CONTEXT_WINDOW_READY,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import format_recent_history, split_key_facts


class SessionContextLoadNode(ChatWorkflowNode):
    """会话窗口装载节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.SESSION_CONTEXT_LOAD,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        """
        处理会话上下文装载逻辑
        
        该方法从Redis中获取会话的上下文信息（包括摘要和历史消息），并更新到状态中。
        如果Redis不可用或出现异常，则将上下文窗口状态设置为降级模式。

        Args:
            state (ChatWorkflowState): 当前工作流状态，包含会话和运行时信息

        Returns:
            ChatWorkflowState: 更新后的状态，包含从Redis获取的上下文信息或降级状态
        """
        # 检查Redis仓库是否可用，如果不可用则设置降级状态
        if not self.dependencies.redis_repo:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            state.session_state.token_budget_total = 0
            return state
        try:
            # 从Redis获取上下文摘要和历史记录
            summary, history = await self.dependencies.redis_repo.get_context(state.runtime.session_id)
            # 更新状态中的最近消息、摘要、关键事实等
            state.session_state.recent_messages = history
            state.session_state.short_summary = summary.core_summary
            state.session_state.key_facts = split_key_facts(summary.key_facts)
            state.session_state.memory_snippets = format_recent_history(history)
            # 计算并更新令牌预算使用情况
            state.session_state.token_budget_used = count_tokens(state.session_state.memory_snippets)
            state.session_state.token_budget_total = max(state.session_state.token_budget_used, 0)
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_READY
        except Exception as exc:
            # 出现异常时，设置降级状态并记录警告日志
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            logger.warning(
                f"Redis 会话窗口装载失败，已降级为空窗口 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
        return state