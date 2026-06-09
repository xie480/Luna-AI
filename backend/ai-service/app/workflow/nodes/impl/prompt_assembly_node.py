"""Prompt 装配节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import ChatWorkflowErrorCode, ChatWorkflowNodeType
from app.workflow.context import ChatErrorState, ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class PromptAssemblyNode(ChatWorkflowNode):
    """Prompt 装配节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.PROMPT_ASSEMBLY,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.CHAT_PROMPT_ASSEMBLY,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.RUNNING),
        )

        if not self.dependencies.prompt_manager:
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CHAT_PROMPT_ASSEMBLY,
                status=ChatStatusState.ERROR,
                display_text="",
                is_visible=False,
                is_terminal=True,
                error="PromptManager 不可用",
            )
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message="PromptManager 不可用，无法装配主 Chat Prompt",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message)
        try:
            system_prompt = await self.dependencies.prompt_manager.assemble_prompt(
                PromptCategory.CHAT,
                state.prompt_state.prompt_variables,
            )
            state.prompt_state.system_prompt_text = system_prompt

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CHAT_PROMPT_ASSEMBLY,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

            return state
        except Exception as exc:
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.CHAT_PROMPT_ASSEMBLY,
                status=ChatStatusState.ERROR,
                display_text="",
                is_visible=False,
                is_terminal=True,
                error=str(exc),
            )
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message=f"Prompt 装配失败: {exc}",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message) from exc

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
