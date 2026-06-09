"""用户画像注入节点。"""

from __future__ import annotations

from typing import Any

from app.logger import logger
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
        """
        处理用户画像注入逻辑
        
        该方法会尝试从用户画像服务获取用户的摘要信息，并将其注入到工作流状态中。
        如果服务不可用或出现异常，则会设置相应的降级标志。
        
        Args:
            state (ChatWorkflowState): 当前工作流状态，包含用户ID和运行时信息
            
        Returns:
            ChatWorkflowState: 更新后的状态，包含用户画像文本或降级信息
        """
        # 标记用户画像注入已执行
        state.profile_state.injection_executed = True
        if not self.dependencies.user_profile_service:
            state.profile_state.prompt_profile_text = ""
            return state
        try:
            # 调用用户画像服务获取摘要信息
            state.profile_state.prompt_profile_text = await self.dependencies.user_profile_service.get_prompt_summary(
                state.runtime.user_id
            )
            if not state.profile_state.prompt_profile_text:
                # 如果没有获取到用户画像文本，设置降级原因
                state.profile_state.degraded_reason = CHAT_WORKFLOW_EMPTY_PROFILE_REASON
        except Exception as exc:
            # 异常处理：设置降级状态并记录警告日志
            state.profile_state.degraded = True
            state.profile_state.degraded_reason = f"用户画像注入失败: {exc}"
            state.profile_state.prompt_profile_text = ""
            logger.warning(
                f"用户画像注入降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
        return state