"""用户画像注入节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import CHAT_WORKFLOW_EMPTY_PROFILE_REASON, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class UserProfileInjectionNode(ChatWorkflowNode):
    """用户画像注入必须节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.USER_PROFILE_INJECTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.USER_PROFILE_INJECTION,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.RUNNING),
        )

        state.profile_state.injection_executed = True
        if not self.dependencies.user_profile_service:
            state.profile_state.prompt_profile_text = ""
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.USER_PROFILE_INJECTION,
                status=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return state
        try:
            state.profile_state.prompt_profile_text = await self.dependencies.user_profile_service.get_prompt_summary(
                state.runtime.user_id
            )
            if not state.profile_state.prompt_profile_text:
                state.profile_state.degraded_reason = CHAT_WORKFLOW_EMPTY_PROFILE_REASON

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.USER_PROFILE_INJECTION,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            state.profile_state.degraded = True
            state.profile_state.degraded_reason = f"用户画像注入失败: {exc}"
            state.profile_state.prompt_profile_text = ""
            logger.warning(
                f"用户画像注入降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.USER_PROFILE_INJECTION,
                status=ChatStatusState.ERROR,
                display_text=get_chat_status_text(ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.ERROR),
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
