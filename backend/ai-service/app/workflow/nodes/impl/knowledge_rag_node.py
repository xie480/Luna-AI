"""知识库 RAG 节点。"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.rag.types import RagSearchRequest
from app.workflow.constants import CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState, KnowledgeCitation
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
        """处理知识库RAG节点的主逻辑。

        Args:
            state: 当前聊天工作流的状态

        Returns:
            更新后的聊天工作流状态
        """
        # 设置知识库状态中的条件进入标志和原因
        state.knowledge_state.entered_by_condition = True
        state.knowledge_state.condition_reason = first_reason(
            state.route_state.route_reasons,
            CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
        )
        state.knowledge_state.retrieval_route = state.route_state.knowledge_route.value

        # 检查RAG编排器是否可用，如果不可用则设置降级模式
        if not self.dependencies.rag_orchestrator:
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = "知识库检索编排器不可用"
            return state

        try:
            # 构建RAG搜索请求并执行搜索
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

            # 更新知识库状态中的证据、提示文本和引用信息
            state.knowledge_state.evidences = response.evidences
            state.knowledge_state.prompt_knowledge_text = response.prompt_context
            state.knowledge_state.citations = [KnowledgeCitation(**item) for item in response.citations]
            state.generation_state.citations = state.knowledge_state.citations
        except Exception as exc:
            # 处理搜索异常，设置降级模式并记录警告日志
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = f"知识库检索失败: {exc}"
            logger.warning(
                f"知识库 RAG 降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
        return state
