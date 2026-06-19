"""主 Chat LLM 节点。

支持两种回复模式：
  1. streaming（默认）：流式逐句生成 + TTS 分段合成，边生成边推送给前端
  2. unified：非流式统一响应，后端等待完整回复 → 解析 → TTS 合成 → 打包一次性下发
"""

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
from app.workflow.nodes.helpers import handle_stream_piece, history_to_model_messages, publish_stream_payload, publish_unified_response


# 非流式统一响应模式的标识值
_UNIFIED_MODE = "unified"


class MainChatLlmNode(ChatWorkflowNode):
    """主 Chat LLM 生成节点。"""

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
        主 Chat LLM 生成入口。

        做什么：根据 input_payload.llm_response_mode 分流到流式或非流式模式。
                流式模式保持原有行为不变；非流式模式执行"等待→解析→TTS→打包下发"四阶段流水线。
        为什么这样做：支持前端按需选择回复模式，同时保持后端控制面不动摇。
        输入输出：
            - 输入/输出：ChatWorkflowState
        边界条件：
            - llm_response_mode 缺失时默认为 streaming
            - 非流式模式下 TTS 合成失败降级为纯文本
        异常行为：
            - 非流式 LLM 调用失败直接抛出异常，由 run_with_observation 捕获审计
        """
        # 读取回复模式（前端传入，默认 streaming）
        llm_response_mode = getattr(state.input_payload, "llm_response_mode", "streaming")

        if llm_response_mode == _UNIFIED_MODE:
            await self._handle_unified(state)
        else:
            await self._handle_streaming(state)

        return state

    # ================================================================
    # 流式模式（保持现有行为不变）
    # ================================================================

    async def _handle_streaming(self, state: ChatWorkflowState) -> None:
        """流式逐句生成 + TTS 分段合成。"""
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
                        tts_enabled = getattr(state.input_payload, "tts_enabled", True)
                        
                        if tts_enabled:
                            emotion_tag = map_emotion(state.generation_state.emotion)
                            # 传递用户选择的 TTS 语言，默认 zh（中文）
                            tts_lang = getattr(state.input_payload, "tts_language", "zh") or "zh"
                            audio_path = await tts_client.synthesize_to_file(
                                chunk_text, emotion=emotion_tag, text_language=tts_lang
                            )
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
                            await publish_stream_payload(
                                state,
                                CHAT_STREAM_TYPE_REPLY_CHUNK,
                                chunk_text,
                                False,
                                self.dependencies.event_publisher,
                                is_sentence_chunk=True,
                            )
                    except Exception as e:
                        from app.logger import logger
                        logger.error("TTS 合成消费任务发生错误: {}", e)
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
                        "主模型生成发生异常，准备进行第 {} 次重试... trace_id={}",
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
                            state.generation_state.full_text += content
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

    # ================================================================
    # 非流式统一响应模式
    # ================================================================

    async def _handle_unified(self, state: ChatWorkflowState) -> None:
        """
        非流式统一响应流水线：等待 LLM → 解析 → TTS → 打包下发。

        做什么：
            1. 推送 LLM_CALLING 状态 → 调用 llm_client.chat_sync() 获取完整回复
            2. 推送 LLM_PARSING 状态 → 尝试使用 StreamParser 提取 thought/emotion/reply；
               若 StreamParser 未能提取有效内容，fallback 将原始响应作为 full_text
            3. 推送 TTS_SYNTHESIZING 状态 → 对完整 reply 文本调用 TTS 合成
            4. 推送 FINAL_RESPONSE 状态 → 调用 publish_unified_response() 一次性下发
        为什么这样做：
            后端等待完整回复后执行同步 TTS 合成，再将文本、音频、情绪等打包为单次 JSON 响应下发。
            前端收到后自行负责语义切分、气泡渲染和音画同步。
            StreamParser 解析失败时 fallback 为纯文本，保证 LLM 的回复不会丢失。
        边界条件：
            - TTS 合成失败时降级为纯文本（audio_uri=None）
            - LLM 调用失败直接上抛异常
            - StreamParser 提取不到 full_text 时使用 raw_response 作为纯文本兜底
            - _publish_chat_status 单点失败不会阻断整个响应流程
        """
        from app.logger import logger
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser
        from app.tts import tts_client, map_emotion

        trace_id = state.runtime.trace_id
        logger.info("[TraceID:{}] 非流式统一响应模式启动", trace_id)

        # ============================================================
        # 阶段 1：调用 LLM 获取完整回复
        # ============================================================
        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.LLM_CALLING,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.LLM_CALLING, ChatStatusState.RUNNING),
        )

        generation_started_at = time.time()
        state.generation_state.generation_started_at_ms = int(generation_started_at * 1000)
        state.generation_state.model_name = llm_client.model_name
        state.generation_state.provider_name = getattr(llm_client, "base_url", "")

        logger.info("[TraceID:{}] LLM 输入参数: {}", trace_id, {
            "system_prompt_snippet": state.prompt_state.system_prompt_text if state.prompt_state.system_prompt_text else "",
            "history_count": len(state.session_state.recent_messages),
            "current_message_snippet": state.input_payload.raw_user_message,
            "trace_id": trace_id,
        })

        try:
            raw_response = await llm_client.chat_sync(
                system_prompt=state.prompt_state.system_prompt_text,
                history=history_to_model_messages(state.session_state.recent_messages),
                current_message=state.input_payload.raw_user_message,
                trace_id=trace_id,
                disambiguated_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                session_id=state.runtime.session_id,
                message_id=state.generation_state.assistant_message_id,
            )
        except Exception:
            # LLM 调用失败，推送 ERROR 状态后上抛
            await self._safe_publish_status(
                state=state,
                stage=ChatStatusStage.LLM_CALLING,
                status=ChatStatusState.ERROR,
                display_text=get_chat_status_text(ChatStatusStage.LLM_CALLING, ChatStatusState.ERROR),
                error="LLM 调用失败",
                is_terminal=True,
            )
            raise

        state.generation_state.e2e_latency_ms = int((time.time() - generation_started_at) * 1000)
        logger.info(
            "[TraceID:{}] LLM 调用完成 e2e_latency_ms={} 原始响应长度={}，原始输出：{}",
            trace_id,
            state.generation_state.e2e_latency_ms,
            len(raw_response),
            raw_response
        )

        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.LLM_CALLING,
            status=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(ChatStatusStage.LLM_CALLING, ChatStatusState.COMPLETED),
        )

        # ============================================================
        # 阶段 2：解析回复（提取 thought / emotion / reply）
        #         解析失败时 fallback 将原始响应全文作为 full_text
        # ============================================================
        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.LLM_PARSING,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.LLM_PARSING, ChatStatusState.RUNNING),
        )

        # 使用 disable_sentence_split=True 模式：不切句，完整保留 reply 原文
        parser = StreamParser(trace_id, disable_sentence_split=True)

        # 一次性喂入完整文本，通过 StreamParser 提取结构化字段
        for msg_type, content in parser.feed(raw_response):
            if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                state.generation_state.full_text += content
            elif msg_type == "thought_content":
                state.generation_state.thought_text += content
            elif msg_type == "emotion_update":
                state.generation_state.emotion = content

        # flush 获取剩余内容
        for msg_type, content in parser.flush():
            if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                state.generation_state.full_text += content
            elif msg_type == "thought_content":
                state.generation_state.thought_text += content
            elif msg_type == "emotion_update":
                state.generation_state.emotion = content

        # === Fallback：StreamParser 未能提取 full_text 时，使用原始响应作为纯文本 ===
        if not state.generation_state.full_text and raw_response.strip():
            logger.warning(
                "[TraceID:{}] StreamParser 未能从 LLM 响应中提取结构化字段，"
                "已降级为纯文本模式（原始响应长度={}）",
                trace_id,
                len(raw_response),
            )
            state.generation_state.full_text = raw_response.strip()

        state.generation_state.finish_reason = "stop"

        logger.info(
            "[TraceID:{}] 解析完成 full_text 长度={} thought_text 长度={} emotion={}",
            trace_id,
            len(state.generation_state.full_text),
            len(state.generation_state.thought_text),
            state.generation_state.emotion or "(空)",
        )

        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.LLM_PARSING,
            status=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(ChatStatusStage.LLM_PARSING, ChatStatusState.COMPLETED),
        )

        # ============================================================
        # 阶段 3：TTS 合成完整音频
        # ============================================================
        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.TTS_SYNTHESIZING,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.TTS_SYNTHESIZING, ChatStatusState.RUNNING),
        )

        audio_uri: str | None = None
        tts_enabled = getattr(state.input_payload, "tts_enabled", True)

        if tts_enabled and state.generation_state.full_text:
            try:
                emotion_tag = map_emotion(state.generation_state.emotion)
                # 传递用户选择的 TTS 语言，默认 zh（中文）
                tts_lang = getattr(state.input_payload, "tts_language", "zh") or "zh"
                audio_path = await tts_client.synthesize_to_file(
                    state.generation_state.full_text, emotion=emotion_tag, text_language=tts_lang
                )
                audio_uri = f"luna://tts/{audio_path.name}"
                logger.info(
                    "[TraceID:{}] TTS 合成完成 audio_uri={} 文本长度={}",
                    trace_id,
                    audio_uri,
                    len(state.generation_state.full_text),
                )
                await self._safe_publish_status(
                    state=state,
                    stage=ChatStatusStage.TTS_SYNTHESIZING,
                    status=ChatStatusState.COMPLETED,
                    display_text=get_chat_status_text(ChatStatusStage.TTS_SYNTHESIZING, ChatStatusState.COMPLETED),
                )
            except Exception as e:
                # TTS 合成失败不阻断主流程，降级为纯文本
                logger.warning(
                    "[TraceID:{}] TTS 合成失败，降级为纯文本: {}",
                    trace_id,
                    e,
                )
                audio_uri = None
                await self._safe_publish_status(
                    state=state,
                    stage=ChatStatusStage.TTS_SYNTHESIZING,
                    status=ChatStatusState.SKIPPED,
                    display_text=get_chat_status_text(ChatStatusStage.TTS_SYNTHESIZING, ChatStatusState.SKIPPED),
                )
        else:
            # TTS 未开启或回复文本为空
            await self._safe_publish_status(
                state=state,
                stage=ChatStatusStage.TTS_SYNTHESIZING,
                status=ChatStatusState.SKIPPED,
                display_text=get_chat_status_text(ChatStatusStage.TTS_SYNTHESIZING, ChatStatusState.SKIPPED),
            )

        # ============================================================
        # 阶段 4：打包并下发统一响应
        # ============================================================
        # 注意：即使 full_text 为空也要下发 publish_unified_response，
        #       保证前端收到流结束信号，否则气泡状态机无法正常流转
        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.FINAL_RESPONSE,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.FINAL_RESPONSE, ChatStatusState.RUNNING),
        )

        await publish_unified_response(
            state=state,
            full_text=state.generation_state.full_text,
            thought_text=state.generation_state.thought_text,
            emotion=state.generation_state.emotion,
            audio_uri=audio_uri,
            finish_reason=state.generation_state.finish_reason,
            event_publisher=self.dependencies.event_publisher,
        )

        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.FINAL_RESPONSE,
            status=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(ChatStatusStage.FINAL_RESPONSE, ChatStatusState.COMPLETED),
            is_terminal=True,
        )

        logger.info(
            "[TraceID:{}] 非流式统一响应流水线完成 e2e_latency_ms={} audio_uri={} full_text 长度={}",
            trace_id,
            state.generation_state.e2e_latency_ms,
            audio_uri or "None",
            len(state.generation_state.full_text),
        )

    # ================================================================
    # 公共辅助
    # ================================================================

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
        """
        发布 Chat 状态通知。

        做什么：通过 ChatStatusPublisher 向前端推送节点执行阶段状态。
        为什么这样做：前端状态栏需要实时感知后端节点执行进展。
        输入输出：
            - 输入：state 工作流状态、stage 阶段、status 状态、display_text 展示文案
            - 输出：通过 SSE 推送给前端
        边界条件：
            - publisher 为 None 时静默跳过
            - 发布失败由 _safe_publish_status 静默捕获
        """
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

    async def _safe_publish_status(
        self,
        state: ChatWorkflowState,
        stage: ChatStatusStage,
        status: ChatStatusState,
        display_text: str,
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        """
        安全的 Chat 状态发布封装，单点失败不阻断主流程。

        做什么：包装 _publish_chat_status，捕获所有异常并记录日志。
        为什么这样做：ChatStatusPublisher 的 publish 可能因网络或内部异常抛出，
                     如果未被捕获会中断整个 _handle_unified 流水线，
                     导致 publish_unified_response 无法执行——这是 LLM 响应丢失的直接原因之一。
        输入输出：同 _publish_chat_status。
        边界条件：
            - 任何失败都会通过 logger.warning 记录，不会抛出异常
            - 不影响主流程继续执行
        """
        try:
            await self._publish_chat_status(
                state=state,
                stage=stage,
                status=status,
                display_text=display_text,
                is_visible=is_visible,
                is_terminal=is_terminal,
                error=error,
            )
        except Exception as e:
            from app.logger import logger
            logger.warning(
                "[TraceID:{}] Chat 状态发布失败(已安全忽略) stage={} status={} error={}",
                state.runtime.trace_id,
                stage.value if hasattr(stage, "value") else stage,
                status.value if hasattr(status, "value") else status,
                e,
            )