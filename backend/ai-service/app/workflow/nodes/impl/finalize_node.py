"""结束归档节点。"""

from __future__ import annotations

from typing import Any

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

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.runtime.current_node_type = ChatWorkflowNodeType.FINALIZE
        return state
