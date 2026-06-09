"""主 Chat LLM 节点。"""

from __future__ import annotations

import time
from typing import Any

from app.workflow.constants import (
    CHAT_STREAM_EMPTY_RESPONSE_ERROR,
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    ChatWorkflowErrorCode,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatErrorState, ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import handle_stream_piece, history_to_model_messages, publish_stream_payload


class MainChatLlmNode(ChatWorkflowNode):
    """主 Chat LLM 流式生成节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.MAIN_CHAT_LLM,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        """
        处理主聊天语言模型节点的核心逻辑
        
        该方法负责与LLM客户端交互，流式获取AI助手的回复，并处理各种状态更新，
        包括错误处理、时间统计、消息解析和事件发布等。
        
        Args:
            state (ChatWorkflowState): 当前工作流的状态对象，包含了会话历史、用户输入、
                                    模型配置和生成状态等信息
            
        Returns:
            ChatWorkflowState: 更新后的状态对象，包含生成的回复文本、错误信息、
                             时间统计等生成状态相关数据
        """
        # 初始化时间和解析器
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser

        started = time.time()
        first_chunk = True
        parser = StreamParser(state.runtime.trace_id)
        # 将历史消息转换为模型可接受的格式
        history_dicts = history_to_model_messages(state.session_state.recent_messages)
        # 设置模型名称和提供商信息
        state.generation_state.model_name = llm_client.model_name
        state.generation_state.provider_name = getattr(llm_client, "base_url", "")
        # 记录流开始时间
        state.generation_state.stream_started_at_ms = int(started * 1000)
        try:
            # 开始从LLM客户端流式获取响应
            async for chunk_data in llm_client.stream_chat_with_context(
                system_prompt=state.prompt_state.system_prompt_text,
                history=history_dicts,
                current_message=state.input_payload.raw_user_message,
                trace_id=state.runtime.trace_id,
                disambiguated_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                session_id=state.runtime.session_id,
                message_id=state.generation_state.assistant_message_id,
            ):
                # 检查是否有错误发生
                if chunk_data.get("error"):
                    state.generation_state.error = str(chunk_data.get("error"))
                # 记录第一次接收数据的时间（Time To First Token）
                if first_chunk and chunk_data.get("chunk"):
                    state.generation_state.ttft_ms = int((time.time() - started) * 1000)
                    first_chunk = False
                # 解析并处理接收到的数据块
                for msg_type, content in parser.feed(chunk_data.get("chunk", "")):
                    await handle_stream_piece(state, msg_type, content, False, self.dependencies.event_publisher)
                # 检查是否完成流式传输
                if chunk_data.get("is_finished", False):
                    # 清空解析器中的剩余内容
                    flushed = parser.flush()
                    if not flushed:
                        # 如果没有剩余内容，则发送空的消息块
                        await publish_stream_payload(
                            state,
                            CHAT_STREAM_TYPE_REPLY_CHUNK,
                            "",
                            True,
                            self.dependencies.event_publisher,
                            error=chunk_data.get("error") or "",
                        )
                    else:
                        # 发送解析器中剩余的内容
                        for msg_type, content in flushed:
                            await handle_stream_piece(
                                state,
                                msg_type,
                                content,
                                True,
                                self.dependencies.event_publisher,
                            )
                    # 记录结束原因
                    state.generation_state.finish_reason = chunk_data.get("finish_reason") or "stop"
                    break
            # 检查是否返回了空响应
            if not state.generation_state.full_text and not state.generation_state.error:
                state.generation_state.error = CHAT_STREAM_EMPTY_RESPONSE_ERROR
        except Exception as exc:
            # 异常处理：记录错误并发布错误消息
            state.generation_state.error = str(exc)
            await publish_stream_payload(
                state,
                CHAT_STREAM_TYPE_REPLY_CHUNK,
                "",
                True,
                self.dependencies.event_publisher,
                error=str(exc),
            )
            # 创建错误状态并抛出异常
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.MAIN_LLM_FAILED.value,
                message=f"主模型生成失败: {exc}",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message) from exc
        return state
