"""Prompt 装配节点。"""

from __future__ import annotations

from typing import Any

from app.prompt.types import PromptCategory
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
        """处理状态并装配系统提示词。
        
        Args:
            state: 聊天工作流状态，包含当前会话的所有状态信息
            
        Returns:
            更新后的聊天工作流状态，其中包含装配好的系统提示词文本
            
        Raises:
            RuntimeError: 当PromptManager不可用或提示词装配失败时抛出异常，
                        并在state中设置相应的错误状态
        """
        # 检查依赖项中的PromptManager是否可用
        if not self.dependencies.prompt_manager:
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message="PromptManager 不可用，无法装配主 Chat Prompt",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message)
        try:
            # 使用PromptManager装配系统提示词
            system_prompt = await self.dependencies.prompt_manager.assemble_prompt(
                PromptCategory.CHAT,
                state.prompt_state.prompt_variables,
            )
            # 将装配好的系统提示词保存到状态中
            state.prompt_state.system_prompt_text = system_prompt
            return state
        except Exception as exc:
            # 处理装配过程中的异常情况
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message=f"Prompt 装配失败: {exc}",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message) from exc