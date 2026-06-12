"""知识库 RAG 节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.rag.types import RagSearchRequest
from app.types.constants import ChatStatusStage, ChatStatusState
from app.rag.types import KnowledgeCitation
from app.workflow.constants import CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import first_reason
from app.config import settings


class KnowledgeRagNode(ChatWorkflowNode):
    """知识库 RAG 条件节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.KNOWLEDGE_RAG,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.knowledge_state.entered_by_condition = True
        state.knowledge_state.condition_reason = first_reason(
            state.route_state.route_reasons,
            CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
        )
        state.knowledge_state.retrieval_route = state.route_state.knowledge_route.value

        if self.dependencies.rag_orchestrator:
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.KNOWLEDGE_RAG,
                status=ChatStatusState.RUNNING,
                display_text=get_chat_status_text(ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.RUNNING),
            )

        if not self.dependencies.rag_orchestrator:
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = "知识库检索编排器不可用"
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.KNOWLEDGE_RAG,
                status=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return state

        try:
            request = RagSearchRequest(
                query=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                route=state.route_state.knowledge_route,
                retrieval_top_k=settings.retrieval_top_k,
                rerank_top_k=settings.rerank_top_k,
                max_retries=3,
                disambiguated_text=state.route_state.disambiguated_text,
                search_queries=state.route_state.external_search_queries,
                temporal_focus=state.route_state.external_temporal_focus or None,
                entity_mentions=state.route_state.external_entity_mentions,
            )
            response = await self.dependencies.rag_orchestrator.search(request, state.runtime.trace_id)

            state.knowledge_state.evidences = response.evidences
            state.knowledge_state.prompt_knowledge_text = response.prompt_context
            state.knowledge_state.citations = [KnowledgeCitation(**item) for item in response.citations]
            state.generation_state.citations = state.knowledge_state.citations

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.KNOWLEDGE_RAG,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = f"知识库检索失败: {exc}"
            logger.warning(
                f"知识库 RAG 降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.KNOWLEDGE_RAG,
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
