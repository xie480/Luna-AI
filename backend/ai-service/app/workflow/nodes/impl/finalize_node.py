"""结束归档节点。"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies


class FinalizeNode(ChatWorkflowNode):
    """结束归档节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.FINALIZE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.runtime.current_node_type = ChatWorkflowNodeType.FINALIZE

        # 整个 DAG 终结信号：不可见 + 终结，触发前端清理所有阶段状态
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.FINALIZE,
            status=ChatStatusState.COMPLETED,
            display_text="",
            is_visible=False,
            is_terminal=True,
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
