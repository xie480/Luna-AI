"""主 Chat LLM 节点。"""

from __future__ import annotations

import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.types.constants import ChatStatusStage, ChatStatusState
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
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser

        started = time.time()
        history_dicts = history_to_model_messages(state.session_state.recent_messages)
        state.generation_state.model_name = llm_client.model_name
        state.generation_state.provider_name = getattr(llm_client, "base_url", "")
        state.generation_state.stream_started_at_ms = int(started * 1000)

        max_retries = 3
        retry_delay = 2.0
        attempt = 0

        while attempt < max_retries:
            first_chunk = True
            parser = StreamParser(state.runtime.trace_id)
            try:
                if attempt > 0:
                    import asyncio
                    from app.logger import logger

                    logger.warning(
                        "主模型生成发生异常，准备进行第 %d 次重试... trace_id=%s",
                        attempt,
                        state.runtime.trace_id,
                    )
                    await asyncio.sleep(retry_delay * attempt)

                    state.generation_state.full_text = ""
                    state.generation_state.thought_text = ""
                    state.generation_state.error = ""
                    state.generation_state.emotion = ""

                async for chunk_data in llm_client.stream_chat_with_context(
                    system_prompt=state.prompt_state.system_prompt_text,
                    history=history_dicts,
                    current_message=state.input_payload.raw_user_message,
                    trace_id=state.runtime.trace_id,
                    disambiguated_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                    session_id=state.runtime.session_id,
                    message_id=state.generation_state.assistant_message_id,
                ):
                    if chunk_data.get("error"):
                        state.generation_state.error = str(chunk_data.get("error"))
                    if first_chunk and chunk_data.get("chunk"):
                        state.generation_state.ttft_ms = int((time.time() - started) * 1000)
                        first_chunk = False

                        # 首个正文 chunk 到达时发布 LLM_STREAMING 运行态
                        # 为什么 is_visible=True, is_terminal=False：
                        #   之前使用 is_visible=False + is_terminal=True 作为"清理前置状态"的手段，
                        #   但这会导致前端的 visualStatusQueueStore 在 _popNext 中遇到 isTerminal &&
                        #   !text 时立即清空队列，使状态栏在 LLM 流式生成期间错误地跳回空闲态。
                        #   现在改为带有文案的可见状态（is_visible=True, is_terminal=False），
                        #   确保在整个流式生成期间前端持续保持在"神经连结供能"激活态，
                        #   直到后续的 COMPLETED / ERROR 或 FinalizeNode 的最终 terminal 到来才退出。
                        await self._publish_chat_status(
                            state=state,
                            stage=ChatStatusStage.LLM_STREAMING,
                            status=ChatStatusState.RUNNING,
                            display_text=get_chat_status_text(ChatStatusStage.LLM_STREAMING, ChatStatusState.RUNNING),
                            is_visible=True,
                            is_terminal=False,
                        )

                    for msg_type, content in parser.feed(chunk_data.get("chunk", "")):
                        await handle_stream_piece(state, msg_type, content, False, self.dependencies.event_publisher)
                    if chunk_data.get("is_finished", False):
                        flushed = parser.flush()
                        for msg_type, content in flushed:
                            await handle_stream_piece(
                                state,
                                msg_type,
                                content,
                                False,
                                self.dependencies.event_publisher,
                            )

                        await publish_stream_payload(
                            state,
                            CHAT_STREAM_TYPE_REPLY_CHUNK,
                            "",
                            True,
                            self.dependencies.event_publisher,
                            error=chunk_data.get("error") or "",
                        )
                        state.generation_state.finish_reason = chunk_data.get("finish_reason") or "stop"
                        break
                if not state.generation_state.full_text and not state.generation_state.error:
                    state.generation_state.error = CHAT_STREAM_EMPTY_RESPONSE_ERROR

                break

            except Exception as exc:
                attempt += 1
                state.generation_state.error = str(exc)
                if attempt >= max_retries:
                    # 全部重试失败，发布可见的 ERROR 状态
                    await self._publish_chat_status(
                        state=state,
                        stage=ChatStatusStage.LLM_STREAMING,
                        status=ChatStatusState.ERROR,
                        display_text=get_chat_status_text(ChatStatusStage.LLM_STREAMING, ChatStatusState.ERROR),
                        is_visible=True,
                        is_terminal=True,
                        error=str(exc),
                    )

                    await publish_stream_payload(
                        state,
                        CHAT_STREAM_TYPE_REPLY_CHUNK,
                        "",
                        True,
                        self.dependencies.event_publisher,
                        error=str(exc),
                    )
                    state.error_state = ChatErrorState(
                        node_type=self.node_type,
                        error_code=ChatWorkflowErrorCode.MAIN_LLM_FAILED.value,
                        message=f"主模型生成失败(已重试 {attempt} 次): {exc}",
                        recoverable=False,
                    )
                    raise RuntimeError(state.error_state.message) from exc

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
