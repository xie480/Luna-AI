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
from app.workflow.context import ChatWorkflowState
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
        import asyncio
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser
        from app.tts import tts_client, map_emotion

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
            sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()

            # 启动 TTS 消费者任务
            async def tts_consumer():
                while True:
                    chunk_text = await sentence_queue.get()
                    if chunk_text is None:
                        sentence_queue.task_done()
                        break
                    
                    try:
                        # 从 state 获取前端传递的 TTS 开关状态
                        # 注意：需要确保前面在 input_payload 里能拿到或传进 state
                        tts_enabled = getattr(state.input_payload, "tts_enabled", True)
                        
                        if tts_enabled:
                            emotion_tag = map_emotion(state.generation_state.emotion)
                            audio_path = await tts_client.synthesize_to_file(chunk_text, emotion=emotion_tag)
                            # 为了绕过前端 CORS 和本地文件限制，我们这里返回特殊的 luna:// 协议 URI
                            audio_uri = f"luna://tts/{audio_path.name}"

                            await publish_stream_payload(
                                state,
                                CHAT_STREAM_TYPE_REPLY_CHUNK,
                                chunk_text,
                                False,
                                self.dependencies.event_publisher,
                                audio_uri=audio_uri,
                                is_sentence_chunk=True,
                            )
                        else:
                            # TTS 未开启，直接发送文本
                            await publish_stream_payload(
                                state,
                                CHAT_STREAM_TYPE_REPLY_CHUNK,
                                chunk_text,
                                False,
                                self.dependencies.event_publisher,
                                is_sentence_chunk=True, # 仍然是句子块，前端可以放入 playbackQueue
                            )
                    except Exception as e:
                        from app.logger import logger
                        logger.error("TTS 合成消费任务发生错误: %s", e)
                        # 降级：仅下发文本，无音频
                        await publish_stream_payload(
                            state,
                            CHAT_STREAM_TYPE_REPLY_CHUNK,
                            chunk_text,
                            False,
                            self.dependencies.event_publisher,
                            is_sentence_chunk=True,
                        )
                    finally:
                        sentence_queue.task_done()

            consumer_task = asyncio.create_task(tts_consumer())

            try:
                if attempt > 0:
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
                        if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                            # 累加全文
                            state.generation_state.full_text += content
                            # 将切分好的断句放入队列等待 TTS 生成音频
                            await sentence_queue.put(content)
                        else:
                            await handle_stream_piece(state, msg_type, content, False, self.dependencies.event_publisher)
                            
                    if chunk_data.get("is_finished", False):
                        flushed = parser.flush()
                        for msg_type, content in flushed:
                            if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                                state.generation_state.full_text += content
                                await sentence_queue.put(content)
                            else:
                                await handle_stream_piece(
                                    state,
                                    msg_type,
                                    content,
                                    False,
                                    self.dependencies.event_publisher,
                                )

                        # 结束流推送前等待所有队列消费完毕
                        await sentence_queue.put(None)
                        await consumer_task

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
                        
                # 如果退出循环时消费者任务还在跑，尝试中止
                if not consumer_task.done():
                    await sentence_queue.put(None)
                    await consumer_task

                # 如果没有正文且报错，或者有 error 需要外层重试
                if state.generation_state.error and not state.generation_state.full_text:
                    raise RuntimeError(f"流式生成中收到错误数据块: {state.generation_state.error}")
                    
                if not state.generation_state.full_text and not state.generation_state.error:
                    state.generation_state.error = CHAT_STREAM_EMPTY_RESPONSE_ERROR
                    raise RuntimeError(f"流式生成无返回内容: {CHAT_STREAM_EMPTY_RESPONSE_ERROR}")

                break

            except Exception as exc:
                # 确保发生异常时结束消费者任务
                if not consumer_task.done():
                    consumer_task.cancel()
                    
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
                    raise RuntimeError(f"主模型生成失败(已重试 {attempt} 次): {exc}") from exc

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
