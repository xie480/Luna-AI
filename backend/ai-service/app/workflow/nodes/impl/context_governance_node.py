"""上下文治理节点。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.context.compression_governor import MemorySlotCompressionGovernor
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
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
    PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY,
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
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.CONTEXT_GOVERNANCE,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.RUNNING),
        )

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        emotion_state = state.route_state.emotion_state

        variables = {
            PROMPT_VARIABLE_CURRENT_TIME: current_time,
            PROMPT_VARIABLE_CURRENT_MESSAGE: state.input_payload.raw_user_message,
            PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
            PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
            PROMPT_VARIABLE_MEMORY_SNIPPETS: state.session_state.memory_snippets,
            PROMPT_VARIABLE_LONG_TERM_MEMORY: state.memory_state.prompt_memory_text,
            PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: state.knowledge_state.prompt_knowledge_text,
            PROMPT_VARIABLE_USER_PROFILE: state.profile_state.prompt_profile_text,
            PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY: state.mcp_tool_state.execution_summary,
            PROMPT_VARIABLE_EMOTION_PRIMARY: str(emotion_state.get("primary_emotion", "")),
            PROMPT_VARIABLE_EMOTION_INTENSITY: f"{float(emotion_state.get('intensity', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_VALENCE: f"{float(emotion_state.get('valence', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_AROUSAL: f"{float(emotion_state.get('arousal', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_TRIGGER: str(emotion_state.get("emotion_trigger", "")),
        }

        try:
            result = await MemorySlotCompressionGovernor().govern(
                trace_id=state.runtime.trace_id,
                session_id=state.runtime.session_id,
                message_id=state.input_payload.frontend_message_id,
                prompt_variables=variables,
            )
            state.prompt_state.prompt_variables = result.updated_variables

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CONTEXT_GOVERNANCE,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            logger.warning(
                f"上下文治理降级使用原始变量 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            state.prompt_state.prompt_variables = variables
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CONTEXT_GOVERNANCE,
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
