"""上下文治理节点。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.context.compression_governor import MemorySlotCompressionGovernor
from app.logger import logger
from app.workflow.constants import (
    PROMPT_VARIABLE_CORE_SUMMARY,
    PROMPT_VARIABLE_CURRENT_MESSAGE,
    PROMPT_VARIABLE_CURRENT_TIME,
    PROMPT_VARIABLE_EMOTION_AROUSAL,
    PROMPT_VARIABLE_EMOTION_INTENSITY,
    PROMPT_VARIABLE_EMOTION_PRIMARY,
    PROMPT_VARIABLE_EMOTION_TRIGGER,
    PROMPT_VARIABLE_EMOTION_VALENCE,
    PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE,
    PROMPT_VARIABLE_KEY_FACTS,
    PROMPT_VARIABLE_LONG_TERM_MEMORY,
    PROMPT_VARIABLE_MEMORY_SNIPPETS,
    PROMPT_VARIABLE_USER_PROFILE,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class ContextGovernanceNode(ChatWorkflowNode):
    """上下文治理节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.CONTEXT_GOVERNANCE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        """
        处理上下文治理逻辑
        
        此方法收集当前会话的各种状态信息，将其组织成变量字典，
        然后通过MemorySlotCompressionGovernor进行治理，最终更新状态中的提示变量。
        
        Args:
            state (ChatWorkflowState): 当前工作流状态，包含用户输入、会话状态、记忆状态等
            
        Returns:
            ChatWorkflowState: 更新后的状态对象，其中prompt_state.prompt_variables被更新为治理后的变量
        """
        # 收集当前时间信息
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        # 获取情绪状态
        emotion_state = state.route_state.emotion_state
        
        # 构建用于提示的变量字典
        variables = {
            PROMPT_VARIABLE_CURRENT_TIME: current_time,
            PROMPT_VARIABLE_CURRENT_MESSAGE: state.input_payload.raw_user_message,
            PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
            PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
            PROMPT_VARIABLE_MEMORY_SNIPPETS: state.session_state.memory_snippets,
            PROMPT_VARIABLE_LONG_TERM_MEMORY: state.memory_state.prompt_memory_text,
            PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: state.knowledge_state.prompt_knowledge_text,
            PROMPT_VARIABLE_USER_PROFILE: state.profile_state.prompt_profile_text,
            PROMPT_VARIABLE_EMOTION_PRIMARY: str(emotion_state.get("primary_emotion", "")),
            PROMPT_VARIABLE_EMOTION_INTENSITY: f"{float(emotion_state.get('intensity', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_VALENCE: f"{float(emotion_state.get('valence', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_AROUSAL: f"{float(emotion_state.get('arousal', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_TRIGGER: str(emotion_state.get("emotion_trigger", "")),
        }
        
        # 尝试通过MemorySlotCompressionGovernor治理变量
        try:
            result = await MemorySlotCompressionGovernor().govern(
                trace_id=state.runtime.trace_id,
                session_id=state.runtime.session_id,
                message_id=state.input_payload.frontend_message_id,
                prompt_variables=variables,
            )
            state.prompt_state.prompt_variables = result.updated_variables
        except Exception as exc:
            # 治理失败时记录警告并使用原始变量
            logger.warning(
                f"上下文治理降级使用原始变量 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            state.prompt_state.prompt_variables = variables
        return state