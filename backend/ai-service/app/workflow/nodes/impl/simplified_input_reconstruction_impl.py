"""Phase 9 简化输入重构节点 — LangGraph 适配器。

做什么：将 SimplifiedInputReconstructionNode 包装为 LangGraph 节点函数，
        读取 ChatWorkflowState 中的会话上下文，调用简化输入重构，
        将结果写入 dag_state。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.workflow.constants import ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.dag.nodes.input_reconstruction_simplified import (
    SimplifiedInputReconstructionNode,
)
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class SimplifiedInputReconstructionImpl(ChatWorkflowNode):
    """简化输入重构节点 — LangGraph 适配器。

    做什么：
    1. 从 ChatWorkflowState 提取会话上下文和用户输入
    2. 调用 SimplifiedInputReconstructionNode 做代词消歧
    3. 将结果写入 dag_state（disambiguated_text、unresolved_pronouns）
    """

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.INPUT_RECONSTRUCTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口。"""
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        """执行简化输入重构。

        做什么：
        1. 从 session_state 提取记忆上下文
        2. 调用 SimplifiedInputReconstructionNode 做代词消歧
        3. 将结果写入 dag_state
        """
        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            logger.warning(
                f"[TraceID:{state.runtime.trace_id}] "
                f"prompt_manager 不可用，简化输入重构降级"
            )
            # 降级：直接使用原始输入
            state.dag_state.disambiguated_text = state.input_payload.raw_user_message
            return state

        # 构建会话上下文
        session_context = {
            "memory_snippets": state.session_state.memory_snippets,
            "key_facts": state.session_state.key_facts,
            "short_summary": state.session_state.short_summary,
            "recent_messages": [
                {"role": m.get("role", ""), "content": m.get("content", "")[:200]}
                for m in (state.session_state.recent_messages or [])[-5:]
            ],
        }

        # 创建简化输入重构节点
        node = SimplifiedInputReconstructionNode(
            prompt_manager=prompt_manager,
            llm_client=prompt_manager.llm_client if hasattr(prompt_manager, 'llm_client') else None,
            chat_status_publisher=self.dependencies.chat_status_publisher,
        )

        # 执行
        result = await node.execute(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            raw_user_message=state.input_payload.raw_user_message,
            session_context=session_context,
        )

        # 将结果写入 dag_state
        state.dag_state.disambiguated_text = result.disambiguated_text
        state.dag_state.unresolved_pronouns = [
            p.model_dump() for p in result.unresolved_pronouns
        ]
        state.dag_state.emotion_state = result.emotion_state

        logger.info(
            f"[TraceID:{state.runtime.trace_id}] "
            f"简化输入重构完成: "
            f"disambiguated_len={len(result.disambiguated_text)}, "
            f"unresolved_count={len(result.unresolved_pronouns)}"
        )

        return state
