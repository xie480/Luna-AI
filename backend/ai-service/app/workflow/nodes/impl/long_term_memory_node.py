"""长期记忆节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import first_reason


class LongTermMemoryNode(ChatWorkflowNode):
    """长期记忆 RAG 条件节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.memory_state.entered_by_condition = True
        state.memory_state.condition_reason = first_reason(
            state.route_state.route_reasons,
            CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
        )

        if self.dependencies.memory_manager:
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.RAG_RETRIEVAL,
                status=ChatStatusState.RUNNING,
                display_text=get_chat_status_text(ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.RUNNING),
            )

        if not self.dependencies.memory_manager:
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = "长期记忆管理器不可用"
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.RAG_RETRIEVAL,
                status=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return state

        try:
            temporal_focus = state.route_state.temporal_focus

            # 闲聊模式降级：使用原始用户消息作为查询词，并强制禁用 Rerank
            if state.runtime.disable_rerank:
                search_queries = [state.input_payload.raw_user_message]
                entity_mentions: list[str] = []
                logger.info(
                    f"闲聊模式记忆检索：禁用 Rerank，使用原始消息作为查询词 "
                    f"trace_id={state.runtime.trace_id} "
                    f"query_text={state.input_payload.raw_user_message!r}"
                )
            else:
                search_queries = state.route_state.search_queries
                entity_mentions = state.route_state.entity_mentions

            text = await self.dependencies.memory_manager.retrieve_and_format_memories(
                query_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                query_vector=[],
                search_queries=search_queries,
                reference_time=temporal_focus.get("reference_time"),
                temporal_deviation=int(temporal_focus.get("temporal_deviation") or 0),
                entity_mentions=entity_mentions,
                disable_rerank=state.runtime.disable_rerank,
            )
            state.memory_state.prompt_memory_text = text

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.RAG_RETRIEVAL,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = f"长期记忆检索失败: {exc}"
            logger.warning(
                f"长期记忆 RAG 降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.RAG_RETRIEVAL,
                status=ChatStatusState.ERROR,
                display_text="",
                is_visible=False,
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
