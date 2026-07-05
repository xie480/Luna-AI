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
from app.prompt.types import PromptCategory
from app.workflow.constants import (
    CHAT_STREAM_EMPTY_RESPONSE_ERROR,
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    PROMPT_VARIABLE_RETRY_ERROR_INFO,
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
        from app.types.constants import (
            WS_MSG_TYPE_EVT_LONG_ANSWER_CREATED,
            WS_MSG_TYPE_EVT_LONG_ANSWER_CHUNK,
            LongAnswerStatus,
        )
        from app.repository.long_answer_pg import LongAnswerPGRepo
        from app.api.sse import sse_manager
        
        answer_mode = state.input_payload.answer_mode
        long_answer_repo = None
        if answer_mode == "long":
            from app.infrastructure.postgres import postgres_client
            session = postgres_client.session_factory()
            long_answer_repo = LongAnswerPGRepo(session)

        started = time.time()
        history_dicts = history_to_model_messages(state.session_state.recent_messages)
        state.generation_state.model_name = llm_client.model_name
        state.generation_state.provider_name = getattr(llm_client, "base_url", "")
        state.generation_state.stream_started_at_ms = int(started * 1000)

        max_retries = 3
        retry_delay = 2.0
        attempt = 0

        # 如果是长回答模式，先创建长回答记录，并推送面板开启事件
        long_answer_model = None
        if answer_mode == "long" and long_answer_repo is not None:
            long_answer_model = await long_answer_repo.create_long_answer(
                interaction_message_id=state.generation_state.assistant_message_id,
                session_id=state.runtime.session_id,
                title="Luna正在整理中……",
                status=LongAnswerStatus.GENERATING.value,
            )
            await sse_manager.publish({
                "type": WS_MSG_TYPE_EVT_LONG_ANSWER_CREATED,
                "trace_id": state.runtime.trace_id,
                "payload": {
                    "schema_version": "1.0",
                    "long_answer_id": long_answer_model.id,
                    "interaction_message_id": state.generation_state.assistant_message_id,
                    "session_id": state.runtime.session_id,
                    "status": "GENERATING",
                    "title": "Luna正在整理中……"
                }
            })

        while attempt < max_retries:
            first_chunk = True
            parser = StreamParser(state.runtime.trace_id)
            sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
            
            # 长回答模式特有状态
            md_content_accumulated = ""
            summary_accumulated = ""
            title_accumulated = ""
            md_chunk_seq = 0

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
                        elif msg_type == "long_answer_chunk" and answer_mode == "long":
                            md_content_accumulated += content
                            md_chunk_seq += 1
                            await sse_manager.publish({
                                "type": WS_MSG_TYPE_EVT_LONG_ANSWER_CHUNK,
                                "trace_id": state.runtime.trace_id,
                                "payload": {
                                    "schema_version": "1.0",
                                    "long_answer_id": long_answer_model.id if long_answer_model else "",
                                    "interaction_message_id": state.generation_state.assistant_message_id,
                                    "seq": md_chunk_seq,
                                    "chunk": content,
                                    "is_finished": False
                                }
                            })
                        elif msg_type == "summary" and answer_mode == "long":
                            summary_accumulated += content
                        elif msg_type == "title" and answer_mode == "long":
                            title_accumulated += content
                        else:
                            await handle_stream_piece(state, msg_type, content, False, self.dependencies.event_publisher)
                            
                    if chunk_data.get("is_finished", False):
                        flushed = parser.flush()
                        for msg_type, content in flushed:
                            if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                                state.generation_state.full_text += content
                                await sentence_queue.put(content)
                            elif msg_type == "replay_translation":
                                state.generation_state.replay_translation_text += content
                                await handle_stream_piece(
                                    state,
                                    msg_type,
                                    content,
                                    False,
                                    self.dependencies.event_publisher,
                                )
                            elif msg_type == "long_answer_chunk" and answer_mode == "long":
                                md_content_accumulated += content
                                md_chunk_seq += 1
                                await sse_manager.publish({
                                    "type": WS_MSG_TYPE_EVT_LONG_ANSWER_CHUNK,
                                    "trace_id": state.runtime.trace_id,
                                    "payload": {
                                        "schema_version": "1.0",
                                        "long_answer_id": long_answer_model.id if long_answer_model else "",
                                        "interaction_message_id": state.generation_state.assistant_message_id,
                                        "seq": md_chunk_seq,
                                        "chunk": content,
                                        "is_finished": True
                                    }
                                })
                            elif msg_type == "summary" and answer_mode == "long":
                                summary_accumulated += content
                            elif msg_type == "title" and answer_mode == "long":
                                title_accumulated += content
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
                        
                        if answer_mode == "long" and long_answer_repo is not None and long_answer_model is not None:
                            from app.repository.long_answer_cache import LongAnswerSummaryCache
                            from app.types.constants import WS_MSG_TYPE_EVT_LONG_ANSWER_COMPLETED
                            
                            await long_answer_repo.update_content(
                                long_answer_model.id,
                                md_content_accumulated,
                                chunk_count=md_chunk_seq,
                                token_count=len(md_content_accumulated) // 2 # 简易估算
                            )
                            
                            generated_title = title_accumulated.strip() if title_accumulated else "Luna 的回答"

                            await long_answer_repo.update_summary(
                                long_answer_model.id,
                                summary_accumulated,
                                title=generated_title
                            )
                            await long_answer_repo.update_status(long_answer_model.id, LongAnswerStatus.COMPLETED.value)
                            
                            # 写入 Redis 缓存
                            await LongAnswerSummaryCache.set_summary(
                                state.runtime.session_id,
                                state.generation_state.assistant_message_id,
                                long_answer_model.id,
                                summary_accumulated,
                                title=generated_title,
                                status=LongAnswerStatus.COMPLETED.value
                            )
                            
                            # 发送完成事件
                            await sse_manager.publish({
                                "type": WS_MSG_TYPE_EVT_LONG_ANSWER_COMPLETED,
                                "trace_id": state.runtime.trace_id,
                                "payload": {
                                    "schema_version": "1.0",
                                    "long_answer_id": long_answer_model.id,
                                    "interaction_message_id": state.generation_state.assistant_message_id,
                                    "status": "COMPLETED"
                                }
                            })

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
                    
                    if answer_mode == "long" and long_answer_repo is not None and long_answer_model is not None:
                        from app.types.constants import WS_MSG_TYPE_EVT_LONG_ANSWER_FAILED
                        await long_answer_repo.update_status(long_answer_model.id, LongAnswerStatus.FAILED.value, error_message=str(exc))
                        await sse_manager.publish({
                            "type": WS_MSG_TYPE_EVT_LONG_ANSWER_FAILED,
                            "trace_id": state.runtime.trace_id,
                            "payload": {
                                "schema_version": "1.0",
                                "long_answer_id": long_answer_model.id,
                                "interaction_message_id": state.generation_state.assistant_message_id,
                                "status": "FAILED",
                                "error": str(exc)
                            }
                        })
                        
                    raise RuntimeError(f"主模型生成失败(已重试 {attempt} 次): {exc}") from exc
        
        if long_answer_repo is not None and 'session' in locals() and hasattr(session, 'close'):
            await session.close()

    # ================================================================
    # 非流式统一响应模式
    # ================================================================

    async def _handle_unified(self, state: ChatWorkflowState) -> None:
        """
        非流式统一响应流水线：等待 LLM → 解析（含 JSON 格式重试）→ TTS → 打包下发。

        做什么：
            1. 推送 LLM_CALLING 状态 → 调用 llm_client.chat_sync() 获取完整回复
            2. 使用 StreamParser 解析 JSON 结构化字段；
               若 StreamParser 未能提取有效结构化字段，构造错误信息注入
               RETRY_ERROR_INFO 变量，重新渲染 system_prompt 后重试（最多 2 次重试）
            3. 推送 TTS_SYNTHESIZING 状态 → 对完整 reply 文本调用 TTS 合成
            4. 推送 FINAL_RESPONSE 状态 → 调用 publish_unified_response() 一次性下发
        为什么这样做：
            后端等待完整回复后执行同步 TTS 合成，再将文本、音频、情绪等打包为单次 JSON 响应下发。
            前端收到后自行负责语义切分、气泡渲染和音画同步。
            当 LLM 输出不符合 JSON 格式时进行重试，将错误信息注入 runtime.j2 的 RETRY_ERROR_INFO
            变量，指导 LLM 修正输出格式。所有重试耗尽后才降级为纯文本兜底。
        边界条件：
            - TTS 合成失败时降级为纯文本（audio_uri=None）
            - LLM 调用失败在重试耗尽后直接上抛异常
            - StreamParser 所有重试均未能提取 full_text 时使用 raw_response 作为纯文本兜底
            - _publish_chat_status 单点失败不会阻断整个响应流程
        """
        import asyncio
        from app.logger import logger
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser
        from app.tts import tts_client, map_emotion

        trace_id = state.runtime.trace_id
        logger.info("[TraceID:{}] 非流式统一响应模式启动", trace_id)

        # ============================================================
        # 阶段 1 + 2（带重试）：LLM 调用与 JSON 结构化解析
        # ============================================================
        # 最大尝试次数：初始调用 1 次 + 2 次重试 = 3 次
        max_retries = 3
        retry_delay = 2.0
        raw_response = ""

        for attempt in range(max_retries):
            # 清理上一次重试的生成状态
            if attempt > 0:
                state.generation_state.full_text = ""
                state.generation_state.thought_text = ""
                state.generation_state.emotion = ""
                state.generation_state.replay_translation_text = ""
                state.generation_state.error = ""

                # 重试：延迟后，将 RETRY_ERROR_INFO 注入 prompt_variables 并重新渲染 Prompt
                await asyncio.sleep(retry_delay * attempt)
                state.prompt_state.prompt_variables[PROMPT_VARIABLE_RETRY_ERROR_INFO] = state.prompt_state.retry_error_info
                state.prompt_state.system_prompt_text = await self.dependencies.prompt_manager.assemble_prompt(
                    PromptCategory.CHAT,
                    state.prompt_state.prompt_variables,
                )
                logger.warning(
                    "[TraceID:{}] JSON 格式重试第 {} 次，已注入修正指令",
                    trace_id, attempt,
                )

            # --- 推送 LLM_CALLING 状态 ---
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

            logger.info("[TraceID:{}] LLM 输入参数 (attempt={}): {}", trace_id, attempt + 1, {
                "system_prompt_snippet": state.prompt_state.system_prompt_text if state.prompt_state.system_prompt_text else "",
                "history_count": len(state.session_state.recent_messages),
                "current_message_snippet": state.input_payload.raw_user_message,
                "trace_id": trace_id,
            })

            # --- 调用 LLM 获取完整回复 ---
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
                if attempt < max_retries - 1:
                    logger.warning(
                        "[TraceID:{}] 第 {} 次 LLM 调用异常，准备重试",
                        trace_id, attempt + 1,
                    )
                    continue
                else:
                    # 最后一次重试仍然失败，推送 ERROR 状态后上抛
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
                "[TraceID:{}] LLM 调用完成 (attempt={}) e2e_latency_ms={} 原始响应长度={} 响应内容：{}",
                trace_id, attempt + 1,
                state.generation_state.e2e_latency_ms,
                len(raw_response),
                raw_response
            )

            # --- 使用 StreamParser 解析结构化 JSON 字段 ---
            parser = StreamParser(trace_id, disable_sentence_split=True)

            for msg_type, content in parser.feed(raw_response):
                if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                    state.generation_state.full_text += content
                elif msg_type == "thought_content":
                    state.generation_state.thought_text += content
                elif msg_type == "emotion_update":
                    state.generation_state.emotion = content

            for msg_type, content in parser.flush():
                if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
                    state.generation_state.full_text += content
                elif msg_type == "thought_content":
                    state.generation_state.thought_text += content
                elif msg_type == "emotion_update":
                    state.generation_state.emotion = content
                elif msg_type == "replay_translation":
                    state.generation_state.replay_translation_text += content

            # --- 判断本次解析是否成功 ---
            # 成功条件：StreamParser 至少提取到了 reply 文本
            has_valid_reply = bool(state.generation_state.full_text)

            if has_valid_reply:
                # 成功提取到结构化字段，退出重试循环
                logger.info(
                    "[TraceID:{}] 第 {} 次尝试解析成功 full_text 长度={} thought_text 长度={} emotion={}",
                    trace_id, attempt + 1,
                    len(state.generation_state.full_text),
                    len(state.generation_state.thought_text),
                    state.generation_state.emotion or "(空)",
                )
                break
            else:
                # 解析失败：StreamParser 未提取到 reply 文本
                # 构造错误信息，供下一次重试的 RETRY_ERROR_INFO 变量使用
                error_detail = "上一轮输出不符合要求的 JSON 格式。"
                if not raw_response.strip():
                    error_detail += " 模型返回了空内容，请确保输出完整 JSON 对象。"
                else:
                    # 根据原始响应的特征分析具体问题
                    if '"reply"' not in raw_response and '"emotion"' not in raw_response:
                        error_detail += " 输出的 JSON 中缺少必需的'emotion'和'reply'字段。"
                    elif '"reply"' not in raw_response:
                        error_detail += " 输出的 JSON 中缺少必需的'reply'字段。"
                    elif '"emotion"' not in raw_response:
                        error_detail += " 输出的 JSON 中缺少必需的'emotion'字段。"
                    else:
                        error_detail += " 输出的 JSON 格式有误（如字符串未正确引号包围、字段名拼写错误等）。"
                    error_detail += " 原始输出片段：" + raw_response.strip()[:500]

                state.prompt_state.retry_error_info = (
                    "## 上一轮输出的格式错误\n"
                    f"{error_detail}\n\n"
                    "## 修正要求\n"
                    "请严格遵循第三章输出格式宪法，仅输出一个合法的单行 JSON 对象。"
                    " 字段必须精确拼写为：check、thought、emotion、reply。"
                )

                if attempt < max_retries - 1:
                    logger.warning(
                        "[TraceID:{}] 第 {} 次尝试解析失败，将重试注入修正指令。错误：{}",
                        trace_id, attempt + 1, error_detail,
                    )
                else:
                    # 所有重试耗尽，使用原始响应作为纯文本兜底
                    logger.warning(
                        "[TraceID:{}] 所有 {} 次尝试均解析失败，降级为纯文本模式（原始响应长度={}）",
                        trace_id, max_retries, len(raw_response),
                    )
                    if raw_response.strip():
                        state.generation_state.full_text = raw_response.strip()
                    break

        # LLM Calling 阶段完成
        await self._safe_publish_status(
            state=state,
            stage=ChatStatusStage.LLM_CALLING,
            status=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(ChatStatusStage.LLM_CALLING, ChatStatusState.COMPLETED),
        )

        # 设置 finish_reason
        state.generation_state.finish_reason = "stop"

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

        # 决定 TTS 合成的源文本：
        # - 当 LLM 返回了 replay_translation 字段时，优先使用该字段作为 TTS 口播文本
        #   （replay_translation 是 LLM 专为语音合成输出的优化文本，如日语翻译等）
        # - 否则使用默认的 full_text（即 reply 字段的原始文本）
        tts_lang = getattr(state.input_payload, "tts_language", "zh") or "zh"
        tts_text = state.generation_state.full_text
        if state.generation_state.replay_translation_text:
            tts_text = state.generation_state.replay_translation_text
            logger.info(
                "[TraceID:{}] TTS 使用 replay_translation 字段长度={}，原 reply 长度={}",
                trace_id,
                len(tts_text),
                len(state.generation_state.full_text),
            )

        if tts_enabled and tts_text:
            try:
                emotion_tag = map_emotion(state.generation_state.emotion)
                audio_path = await tts_client.synthesize_to_file(
                    tts_text, emotion=emotion_tag, text_language=tts_lang
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