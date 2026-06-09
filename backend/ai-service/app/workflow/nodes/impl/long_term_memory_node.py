"""长期记忆节点。"""

from __future__ import annotations

from typing import Any

from app.logger import logger
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
        """
        处理长期记忆检索逻辑
        
        Args:
            state (ChatWorkflowState): 当前工作流状态
            
        Returns:
            ChatWorkflowState: 更新后的状态，包含长期记忆信息或错误状态
        """
        # 标记进入条件节点
        state.memory_state.entered_by_condition = True
        state.memory_state.condition_reason = first_reason(
            state.route_state.route_reasons,
            CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
        )
        
        # 检查内存管理器是否可用
        if not self.dependencies.memory_manager:
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = "长期记忆管理器不可用"
            return state
            
        try:
            # 获取时间焦点参数
            temporal_focus = state.route_state.temporal_focus
            # 从内存管理器检索并格式化记忆
            text = await self.dependencies.memory_manager.retrieve_and_format_memories(
                query_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                query_vector=[],
                search_queries=state.route_state.search_queries,
                reference_time=temporal_focus.get("reference_time"),
                temporal_deviation=int(temporal_focus.get("temporal_deviation") or 0),
                entity_mentions=state.route_state.entity_mentions,
            )
            # 将检索到的记忆文本存储到状态中
            state.memory_state.prompt_memory_text = text
        except Exception as exc:
            # 设置降级状态并记录错误原因
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = f"长期记忆检索失败: {exc}"
            logger.warning(
                f"长期记忆 RAG 降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
        return state