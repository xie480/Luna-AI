"""会话上下文装载节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.llm.context_manager import count_tokens
from app.types.constants import ChatStatusStage, ChatStatusState
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
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.RUNNING),
        )

        if not self.dependencies.redis_repo:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            state.session_state.token_budget_total = 0
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return state
        try:
            summary, history = await self.dependencies.redis_repo.get_context(state.runtime.session_id)
            state.session_state.recent_messages = history
            state.session_state.short_summary = summary.core_summary
            state.session_state.key_facts = split_key_facts(summary.key_facts)
            state.session_state.memory_snippets = format_recent_history(history)
            state.session_state.token_budget_used = count_tokens(state.session_state.memory_snippets)
            state.session_state.token_budget_total = max(state.session_state.token_budget_used, 0)
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_READY

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            logger.warning(
                f"Redis 会话窗口装载失败，已降级为空窗口 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.ERROR,
                display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.ERROR),
                is_terminal=True,
                error=str(exc),
            )
        return state

    async def _publish_chat_status(
        self,
        state: ChatWorkflowState,
        stage: ChatStatusStage,
        status: ChatStatusState,
        display_text: str,
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
        if publisher is None:
            return
        await publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=stage,
            state=status,
            display_text=display_text,
            is_visible=is_visible,
            is_terminal=is_terminal,
            error=error,
        )
