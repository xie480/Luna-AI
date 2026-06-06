"""
Luna AI HTTP API 服务模块

做什么：提供 RESTful HTTP API 替代原有的 WebSocket 业务路由。
废弃 WebSocket 后，所有业务接口统一通过 HTTP POST/GET 调用，流式推送通过 SSE 实现。

接口列表：
    - GET  /api/calendar     获取日历元数据
    - GET  /api/chat_history  获取指定日期聊天记录
    - POST /api/init_state    同步初始状态
    - POST /api/chat          发送聊天请求（流式输出通过 SSE 推送）

边界条件：
    - 统一响应结构 {type, trace_id, payload} 兼容旧 WSMessage
    - trace_id 从 HTTP Header "X-Trace-ID" 获取，若不存在则自动生成
异常行为：
    - 参数校验失败返回 400
    - 内部错误返回 500，JSON 结构包含 type=ERROR
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, ChatSummary, Interaction
from app.repository.models import InteractionModel
from app.types.constants import (
    WS_MSG_TYPE_CHAT_STREAM,
    WS_MSG_TYPE_ERROR,
    WS_MSG_TYPE_EVT_INIT_STATE,
    WS_MSG_TYPE_RES_CALENDAR_METADATA,
    WS_MSG_TYPE_RES_CHAT_HISTORY,
    Role,
)
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api", tags=["api"])


# ============================================================
# 共享模型定义
# ============================================================


class APIResponse(BaseModel):
    """统一 HTTP API 响应结构，与旧 WSMessage 保持字段兼容"""
    type: str
    trace_id: str
    payload: Any


class ChatMessage(BaseModel):
    """定义单条对话消息"""
    role: str
    content: str
    thought: str = ""


class ChatStreamPayload(BaseModel):
    """定义 Chat 流式响应的 Payload"""
    type: str
    chunk: str
    is_finished: bool
    node_id: str
    error: str = ""


class InteractionQA(BaseModel):
    """用于前端展示的单轮问答结构"""
    msgId: str
    userContent: str
    assistantContent: str
    timestamp: int


class InitStateRequestPayload(BaseModel):
    """初始状态请求 Payload"""
    sessionId: str = ""


class ChatRequestPayload(BaseModel):
    """聊天请求 Payload"""
    sessionId: str
    message: str
    msgId: str
    history: List[ChatMessage] = []


# ============================================================
# 依赖注入
# ============================================================


async def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """
    从请求头获取 trace_id，若不存在则自动生成。
    确保全链路追踪标识贯穿始终。
    """
    return x_trace_id or generate_string_id()


async def get_pg_repo(request: Request) -> Optional[ChatHistoryPGRepo]:
    """从 app.state 获取 PostgreSQL 仓库实例"""
    return getattr(request.app.state, "pg_repo", None)


async def get_redis_repo(request: Request) -> Optional[ChatHistoryRedisRepo]:
    """从 app.state 获取 Redis 仓库实例"""
    return getattr(request.app.state, "redis_repo", None)


async def get_prompt_manager(request: Request) -> Optional[PromptManager]:
    """从 app.state 获取 PromptManager 实例"""
    return getattr(request.app.state, "prompt_manager", None)


async def get_memory_manager(request: Request) -> Optional[MemoryManager]:
    """从 app.state 获取 MemoryManager 实例"""
    return getattr(request.app.state, "memory_manager", None)


# ============================================================
# 实用函数：推送 SSE 事件
# ============================================================


async def _publish_sse_event(trace_id: str, event_type: str, payload: Any) -> None:
    """
    通过全局 SSE 管理器推送事件到所有连接的客户端。

    做什么：将流式聊天片段包装为事件，通过 sse_manager 推送给前端。
    为什么这样做：SSE 连接由 sse_manager 统一管理，HTTP API 无需关心连接细节。
    """
    try:
        from app.api.sse import sse_manager
        await sse_manager.publish({
            "type": event_type,
            "trace_id": trace_id,
            "payload": payload,
        })
    except Exception as e:
        logger.error(f"推送 SSE 事件失败 trace_id={trace_id} error={e}")


# ============================================================
# 业务接口实现
# ============================================================


@router.get("/calendar", response_model=APIResponse)
async def get_calendar_metadata(
    year_month: str,
    trace_id: str = Depends(get_trace_id),
    pg_repo: Optional[ChatHistoryPGRepo] = Depends(get_pg_repo),
) -> APIResponse:
    """
    获取指定年月的日历元数据（有聊天记录的天数列表）。

    替代原有的 REQ_GET_CALENDAR_METADATA WebSocket 消息。
    输入：year_month 格式 "YYYY-MM"
    输出：{ year_month, active_dates }
    """
    if not year_month:
        raise HTTPException(status_code=400, detail="year_month is required")

    active_dates: List[str] = []
    if pg_repo:
        try:
            active_dates = await pg_repo.get_active_dates_by_month(year_month)
        except Exception as e:
            logger.error(f"获取日历元数据失败 trace_id={trace_id} error={e}", exc_info=True)
            raise HTTPException(status_code=500, detail="数据库错误")

    return APIResponse(
        type=WS_MSG_TYPE_RES_CALENDAR_METADATA,
        trace_id=trace_id,
        payload={"year_month": year_month, "active_dates": active_dates},
    )


@router.get("/chat_history", response_model=APIResponse)
async def get_chat_history(
    date: str,
    trace_id: str = Depends(get_trace_id),
    pg_repo: Optional[ChatHistoryPGRepo] = Depends(get_pg_repo),
) -> APIResponse:
    """
    获取指定日期的详细聊天记录。

    替代原有的 REQ_GET_CHAT_HISTORY WebSocket 消息。
    输入：date 格式 "YYYY-MM-DD"
    输出：{ date, messages }
    """
    if not date:
        raise HTTPException(status_code=400, detail="date is required")

    interactions: List[InteractionModel] = []
    if pg_repo:
        try:
            interactions = await pg_repo.get_interactions_by_date(date)
        except Exception as e:
            logger.error(f"获取聊天记录失败 trace_id={trace_id} error={e}", exc_info=True)
            raise HTTPException(status_code=500, detail="数据库错误")

    messages = []
    for interaction in interactions:
        # 用户消息
        messages.append({
            "id": interaction.message_id,
            "role": Role.USER.value,
            "content": interaction.user_content,
            "created_at": interaction.created_at.isoformat(),
        })
        # 助手消息：携带 thought（内心独白）和 emotion（情绪）字段
        content = interaction.assistant_content
        if interaction.error:
            content = interaction.error
        messages.append({
            "id": interaction.id,
            "role": Role.ASSISTANT.value,
            "content": content,
            "thought": interaction.thought,
            "emotion": interaction.emotion,
            "created_at": interaction.created_at.isoformat(),
        })

    return APIResponse(
        type=WS_MSG_TYPE_RES_CHAT_HISTORY,
        trace_id=trace_id,
        payload={"date": date, "messages": messages},
    )


@router.post("/init_state", response_model=APIResponse)
async def sync_init_state(
    payload: InitStateRequestPayload,
    trace_id: str = Depends(get_trace_id),
    redis_repo: Optional[ChatHistoryRedisRepo] = Depends(get_redis_repo),
) -> APIResponse:
    """
    同步前端初始状态，返回当前会话的近三轮对话记录。

    替代原有的 CMD_SYNC_INIT_STATE WebSocket 消息。
    输入：{ sessionId }
    输出：{ sessionId, recentQA }
    """
    logger.info(f"收到 /api/init_state 请求 trace_id={trace_id} payload={payload.model_dump()}")
    session_id = payload.sessionId or datetime.now().strftime("%Y%m%d")

    recent_history: List[Interaction] = []
    if redis_repo:
        try:
            _, recent_history = await redis_repo.get_context(session_id)
        except Exception as e:
            logger.error(f"从 Redis 获取上下文失败 trace_id={trace_id} error={e}")

    start_index = 0
    if len(recent_history) > 3:
        start_index = len(recent_history) - 3
    last_3_history = recent_history[start_index:]

    recent_qa = []
    for h in last_3_history:
        recent_qa.append(InteractionQA(
            msgId=h.msgId,
            userContent=h.userContent,
            assistantContent=h.assistantContent,
            timestamp=h.timestamp,
        ))

    result_payload = {
        "sessionId": session_id,
        "recentQA": [qa.model_dump() for qa in recent_qa],
    }

    return APIResponse(
        type=WS_MSG_TYPE_EVT_INIT_STATE,
        trace_id=trace_id,
        payload=result_payload,
    )


@router.get("/test_reload")
async def test_reload():
    return {"status": "reloaded"}


@router.post("/chat")
async def chat_request(
    payload: ChatRequestPayload,
    trace_id: str = Depends(get_trace_id),
    redis_repo: Optional[ChatHistoryRedisRepo] = Depends(get_redis_repo),
    pg_repo: Optional[ChatHistoryPGRepo] = Depends(get_pg_repo),
    prompt_mgr: Optional[PromptManager] = Depends(get_prompt_manager),
    memory_manager: Optional[MemoryManager] = Depends(get_memory_manager),
) -> APIResponse:
    """
    处理聊天请求，执行完整的流式对话流程。

    替代原有的 CMD_USER_INPUT WebSocket 消息。
    流程：
    1. 从 Redis 加载上下文
    2. 组装 Input Reconstruction Prompt
    3. 调用 InputReconstructor 消歧
    4. 组装 Chat Prompt
    5. 通过 asyncio.create_task 在后台执行 LLM 流式调用和 SSE 推送
    6. 立即返回 HTTP 响应

    返回：立即返回 { status: "streaming", msgId }，实际流式内容通过 SSE 推送。
    """
    print(f"DEBUG: Reached chat_request! trace_id={trace_id}")
    logger.info(f"收到 /api/chat 请求 trace_id={trace_id} sessionId={payload.sessionId} msgId={payload.msgId}")
    if not payload.sessionId:
        raise HTTPException(status_code=400, detail="sessionId is required")
    if not payload.message:
        raise HTTPException(status_code=400, detail="message is required")

    user_msg_id = payload.msgId or generate_string_id()

    # ---- 1. 加载上下文 ----
    summary = ChatSummary()
    recent_history: List[Interaction] = []
    if redis_repo:
        try:
            summary, recent_history = await redis_repo.get_context(payload.sessionId)
        except Exception as e:
            logger.error(f"从 Redis 获取上下文失败 trace_id={trace_id} error={e}")

    # ---- 2. 组装上下文文本 ----
    memory_snippets_parts = []
    for i, h in enumerate(recent_history):
        memory_snippets_parts.append(f"[对话 {i+1}]\n")
        memory_snippets_parts.append(f"用户: {h.userContent}\n")
        if h.assistantContent:
            memory_snippets_parts.append(f"Luna: {h.assistantContent}\n")
        if h.thought:
            memory_snippets_parts.append(f"(内心独白: {h.thought})\n")
        if h.emotion:
            memory_snippets_parts.append(f"(心情: {h.emotion})\n")
        if h.error:
            memory_snippets_parts.append(f"(错误: {h.error})\n")
        if h.timestamp:
            timestamp_str = datetime.fromtimestamp(h.timestamp).strftime("%Y-%m-%d %H:%M:%S %A")
            memory_snippets_parts.append(f"(时间: {timestamp_str})\n")
        memory_snippets_parts.append("\n")
    memory_snippets = "".join(memory_snippets_parts)

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    prompt_variables: Dict[str, str] = {
        "CURRENT_TIME": current_time,
        "CORE_SUMMARY": summary.core_summary,
        "KEY_FACTS": summary.key_facts,
        "MEMORY_SNIPPETS": memory_snippets,
    }

    # ---- 3. 组装 Input Reconstruction Prompt ----
    input_recon_system_prompt = ""
    input_recon_memory_prompt = ""
    input_recon_runtime_prompt = ""

    if prompt_mgr:
        try:
            input_recon_system_prompt = await prompt_mgr.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION, {}
            )
            input_recon_memory_prompt = await prompt_mgr.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION, {
                    "CORE_SUMMARY": summary.core_summary,
                    "KEY_FACTS": summary.key_facts,
                    "MEMORY_SNIPPETS": memory_snippets,
                }
            )
            from app.types.constants import PrimaryIntent, IntentCategory, DagRouteHint, RetrievalType
            primary_intents = [i.value for i in PrimaryIntent]
            categories = [c.value for c in IntentCategory]
            dag_route_hints = [h.value for h in DagRouteHint]
            retrieval_types = [r.value for r in RetrievalType]

            input_recon_runtime_prompt = await prompt_mgr.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION, {
                    "USER_INPUT": payload.message,
                    "PRIMARY_INTENTS": '"' + '", "'.join(primary_intents) + '"',
                    "CATEGORIES": '"' + '", "'.join(categories) + '"',
                    "DAG_ROUTE_HINTS": '"' + '", "'.join(dag_route_hints) + '"',
                    "RETRIEVAL_TYPES": '"' + '", "'.join(retrieval_types) + '"',
                }
            )
        except Exception as e:
            logger.error(f"组装 Input Reconstruction Prompt 失败 trace_id={trace_id} error={e}")

    logger.info(f"组装 Input Reconstruction Prompt 成功 trace_id={trace_id}, input_recon_system_prompt={input_recon_system_prompt}, input_recon_memory_prompt={input_recon_memory_prompt}, input_recon_runtime_prompt={input_recon_runtime_prompt}")

    # ---- 4. 调用 Input Reconstruction Agent ----
    from app.agent.input_reconstructor import InputReconstructorAgent
    from app.llm.client import llm_client

    agent = InputReconstructorAgent(llm_client)
    disambiguated_text = payload.message
    recon_data = None
    long_term_memory_trigger = False
    search_queries = []
    reference_time = None
    entity_mentions = []
    
    try:
        recon_result = await agent.process(
            trace_id=trace_id,
            user_input=payload.message,
            system_prompt=input_recon_system_prompt,
            memory_prompt=input_recon_memory_prompt,
            runtime_prompt=input_recon_runtime_prompt,
        )
        recon_data = recon_result.model_dump()
        emotion_state = recon_data.get("emotion_state", {})
        reconstruction = recon_data.get("reconstruction", {})
        disambiguated_text = reconstruction.get("disambiguated_text", payload.message)

        retrieval_routing = recon_data.get("retrieval_routing", {})
        long_term_memory_routing = retrieval_routing.get("long_term_memory", {})
        long_term_memory_trigger = long_term_memory_routing.get("trigger", False)
        search_queries = long_term_memory_routing.get("search_queries", [])
        temporal_focus = long_term_memory_routing.get("temporal_focus", {})
        reference_time = temporal_focus.get("reference_time")
        temporal_deviation = temporal_focus.get("temporal_deviation", 0)
        entity_mentions = long_term_memory_routing.get("entity_mentions", [])

        prompt_variables["EMOTION_PRIMARY"] = emotion_state.get("primary_emotion", "")
        prompt_variables["EMOTION_INTENSITY"] = f"{emotion_state.get('intensity', 0.0):.2f}"
        prompt_variables["EMOTION_VALENCE"] = f"{emotion_state.get('valence', 0.0):.2f}"
        prompt_variables["EMOTION_AROUSAL"] = f"{emotion_state.get('arousal', 0.0):.2f}"
        prompt_variables["EMOTION_TRIGGER"] = emotion_state.get("emotion_trigger", "")
    except Exception as e:
        logger.error(f"调用 InputReconstruction 失败 trace_id={trace_id} error={e}")

    logger.info(f"调用 InputReconstruction 成功 trace_id={trace_id}, recon_data={recon_data}")

    # ---- 5. 混合检索 RAG：从长期记忆中召回并注入 Prompt ----
    # 为什么这样做：Phase 6 -> Phase 7 过渡的核心环节，
    # 通过 BM25 + 向量双路召回和 Rerank 重排，将高价值长期记忆注入 Chat Prompt。
    # 检索依赖 disambiguated_text（消歧后的用户输入），在 InputReconstructor 完成后执行。
    if memory_manager and long_term_memory_trigger:
        try:
            # 调用混合检索 -> 格式化 -> 返回 'date: ...\ncontent: ...' 文本
            long_term_memory_text = await memory_manager.retrieve_and_format_memories(
                query_text=disambiguated_text,
                query_vector=[],
                search_queries=search_queries,
                reference_time=reference_time,
                entity_mentions=entity_mentions,
            )
            prompt_variables["LONG_TERM_MEMORY"] = long_term_memory_text
            logger.info(f"长期记忆 RAG 检索注入成功 trace_id={trace_id} text_length={len(long_term_memory_text)}")
        except Exception as e:
            logger.warning(f"长期记忆 RAG 检索注入失败（降级跳过） trace_id={trace_id} error={e}")
            prompt_variables["LONG_TERM_MEMORY"] = ""
    elif memory_manager and not long_term_memory_trigger:
        logger.info(f"长期记忆检索未触发 (trigger=False) trace_id={trace_id}")
        prompt_variables["LONG_TERM_MEMORY"] = ""
    else:
        logger.info(f"记忆管理器不可用，跳过长期记忆 RAG 检索 trace_id={trace_id}")
        prompt_variables["LONG_TERM_MEMORY"] = ""

    # ---- 6. 组装完整 Chat Prompt ----
    full_system_prompt = ""
    if prompt_mgr:
        try:
            full_system_prompt = await prompt_mgr.assemble_prompt(
                PromptCategory.CHAT, prompt_variables,
            )
        except Exception as e:
            logger.error(f"组装 Chat Prompt 失败 trace_id={trace_id} error={e}")

    logger.info(f"开始流式对话 trace_id={trace_id}, full_system_prompt={full_system_prompt}")

    # ---- 6. 将流式调用与持久化放入后台 Task，立即返回 HTTP 响应 ----
    asyncio.create_task(
        _execute_llm_stream(
            trace_id=trace_id,
            session_id=payload.sessionId,
            user_msg_id=user_msg_id,
            full_system_prompt=full_system_prompt,
            recent_history=recent_history,
            user_message=payload.message,
            disambiguated_text=disambiguated_text,
            pg_repo=pg_repo,
            redis_repo=redis_repo,
            prompt_mgr=prompt_mgr,
        )
    )

    return APIResponse(
        type=WS_MSG_TYPE_CHAT_STREAM,
        trace_id=trace_id,
        payload={"status": "streaming", "msgId": user_msg_id},
    )


async def _execute_llm_stream(
    trace_id: str,
    session_id: str,
    user_msg_id: str,
    full_system_prompt: str,
    recent_history: List[Interaction],
    user_message: str,
    disambiguated_text: str,
    pg_repo: Optional[ChatHistoryPGRepo],
    redis_repo: Optional[ChatHistoryRedisRepo],
    prompt_mgr: Optional[PromptManager],
) -> None:
    """
    在后台执行 LLM 流式调用、SSE 推送和持久化。

    做什么：在独立的 asyncio.Task 中执行 LLM 流式调用和 SSE 推送，
            不阻塞 chat_request 的 HTTP 响应返回。
    为什么这样做：分离 HTTP 响应与 LLM 流式执行的生命周期。
    """
    start_time = time.time()
    is_first_chunk = True
    full_assistant_content = ""
    full_assistant_thought = ""
    full_assistant_emotion = ""
    stream_error: Optional[Exception] = None

    try:
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser

        history_dicts = []
        for h in recent_history:
            history_dicts.append({"role": Role.USER.value, "content": h.userContent})
            content = h.assistantContent
            if h.error:
                content = h.error
            history_dicts.append({"role": Role.ASSISTANT.value, "content": content})

        parser = StreamParser(trace_id)

        async for chunk_data in llm_client.stream_chat_with_context(
            system_prompt=full_system_prompt,
            history=history_dicts,
            current_message=user_message,
            trace_id=trace_id,
            disambiguated_text=disambiguated_text,
        ):
            if chunk_data.get("error"):
                stream_error = Exception(chunk_data.get("error"))
                logger.error(f"LLM 返回流式错误 trace_id={trace_id} error={chunk_data.get('error')}")

            if is_first_chunk and chunk_data.get("chunk"):
                ttft = int((time.time() - start_time) * 1000)
                logger.info(f"首字延迟 (TTFT) trace_id={trace_id} ttft_ms={ttft}")
                is_first_chunk = False
            logger.debug(f"LLM 推送 chunk trace_id={trace_id} chunk={chunk_data.get('chunk')}")

            raw_chunk = chunk_data.get("chunk", "")
            msgs = parser.feed(raw_chunk)

            for msg_type, content in msgs:
                if msg_type == "reply_chunk":
                    full_assistant_content += content
                elif msg_type == "thought_content":
                    full_assistant_thought += content
                elif msg_type == "emotion_update":
                    full_assistant_emotion = content

                if msg_type != "thought_content":
                    chat_payload = ChatStreamPayload(
                        type=msg_type,
                        chunk=content,
                        is_finished=False,
                        node_id=user_msg_id,
                        error="",
                    )
                    await _publish_sse_event(
                        trace_id, WS_MSG_TYPE_CHAT_STREAM, chat_payload.model_dump(),
                    )

            # 流结束处理
            if chunk_data.get("is_finished", False):
                flush_msgs = parser.flush()
                if not flush_msgs:
                    chat_payload = ChatStreamPayload(
                        type="reply_chunk", chunk="", is_finished=True,
                        node_id=user_msg_id, error=chunk_data.get("error") or "",
                    )
                    await _publish_sse_event(
                        trace_id, WS_MSG_TYPE_CHAT_STREAM, chat_payload.model_dump(),
                    )
                else:
                    for f_type, f_content in flush_msgs:
                        if f_type == "reply_chunk":
                            full_assistant_content += f_content
                        elif f_type == "thought_content":
                            full_assistant_thought += f_content
                        elif f_type == "emotion_update":
                            full_assistant_emotion = f_content

                        chat_payload = ChatStreamPayload(
                            type=f_type, chunk=f_content, is_finished=True,
                            node_id=user_msg_id, error=chunk_data.get("error") or "",
                        )
                        await _publish_sse_event(
                            trace_id, WS_MSG_TYPE_CHAT_STREAM, chat_payload.model_dump(),
                        )
                break

    except Exception as e:
        logger.error(f"ChatStream 处理异常 trace_id={trace_id} error={e}")
        stream_error = e
        chat_payload = ChatStreamPayload(
            type="reply_chunk", chunk="", is_finished=True,
            node_id=user_msg_id, error=str(e),
        )
        await _publish_sse_event(
            trace_id, WS_MSG_TYPE_CHAT_STREAM, chat_payload.model_dump(),
        )

    # ---- 7. 异步持久化 ----
    await _persist_interaction(
        user_msg_id=user_msg_id,
        session_id=session_id,
        user_message=user_message,
        assistant_content=full_assistant_content,
        thought=full_assistant_thought,
        emotion=full_assistant_emotion,
        stream_error=stream_error,
        pg_repo=pg_repo,
        redis_repo=redis_repo,
        prompt_mgr=prompt_mgr,
        trace_id=trace_id,
    )


# ============================================================
# 异步持久化与压缩
# ============================================================


async def _persist_interaction(
    user_msg_id: str,
    session_id: str,
    user_message: str,
    assistant_content: str,
    thought: str,
    emotion: str,
    stream_error: Optional[Exception],
    pg_repo: Optional[ChatHistoryPGRepo],
    redis_repo: Optional[ChatHistoryRedisRepo],
    prompt_mgr: Optional[PromptManager],
    trace_id: str,
) -> None:
    """
    异步持久化对话记录。

    做什么：在流式输出结束后，将完整的问答记录异步写入 PostgreSQL 和 Redis。
    为什么这样做：不阻塞主请求流程，确保用户能立即收到 SSE 流响应。
    """
    now_ts = int(time.time())

    error_json = ""
    if stream_error:
        err_data = {"error": "generation_failed", "details": str(stream_error)}
        error_json = json.dumps(err_data)
        if not assistant_content:
            assistant_content = error_json
    elif not assistant_content:
        err_data = {"error": "generation_failed", "details": "Assistant returned empty content"}
        error_json = json.dumps(err_data)
        assistant_content = error_json

    interaction = Interaction(
        msgId=user_msg_id,
        userContent=user_message,
        assistantContent=assistant_content,
        thought=thought,
        emotion=emotion,
        error=error_json,
        timestamp=now_ts,
    )

    interaction_model = InteractionModel(
        id=generate_string_id(),
        session_id=session_id,
        message_id=user_msg_id,
        user_content=user_message,
        assistant_content=assistant_content,
        thought=thought,
        emotion=emotion,
        error=error_json,
    )

    if pg_repo:
        try:
            await pg_repo.save_interaction(interaction_model)
        except Exception as e:
            logger.error(f"异步保存 Interaction 到 PG 失败 trace_id={trace_id} error={e}")

    if redis_repo:
        try:
            length = await redis_repo.save_interaction(session_id, interaction)
            from app.repository.chat_history_redis import MEM_WORKING_WINDOW_SIZE
            if length > MEM_WORKING_WINDOW_SIZE:
                await _trigger_compression(
                    session_id=session_id,
                    trace_id=trace_id,
                    redis_repo=redis_repo,
                    prompt_mgr=prompt_mgr,
                )
        except Exception as e:
            logger.error(f"异步保存 Interaction 到 Redis 失败 trace_id={trace_id} error={e}")


async def _trigger_compression(
    session_id: str,
    trace_id: str,
    redis_repo: Optional[ChatHistoryRedisRepo],
    prompt_mgr: Optional[PromptManager],
) -> None:
    """
    触发上下文摘要压缩流程：将早期对话压缩为核心摘要，裁剪历史。

    做什么：当 Redis 中短期会话记录超过窗口大小时，调用 LLM 压缩旧记录为摘要。
    """
    if not redis_repo:
        return
    logger.info(f"触发摘要压缩 session_id={session_id} trace_id={trace_id}")

    try:
        summary, history = await redis_repo.get_context(session_id)
    except Exception as e:
        logger.error(f"获取上下文失败，无法进行压缩 trace_id={trace_id} error={e}")
        return

    from app.repository.chat_history_redis import MEM_WORKING_WINDOW_SIZE, MEM_COMPRESS_BATCH_SIZE

    if len(history) <= MEM_WORKING_WINDOW_SIZE:
        logger.info(f"历史记录未超过阈值，无需压缩 count={len(history)} threshold={MEM_WORKING_WINDOW_SIZE}")
        return

    compress_count = min(MEM_COMPRESS_BATCH_SIZE, len(history))

    messages_text_parts = []
    for i in range(compress_count):
        interaction = history[i]
        messages_text_parts.append(f"用户: {interaction.userContent}\n")
        messages_text_parts.append(f"Luna: {interaction.assistantContent}\n")
        if interaction.thought:
            messages_text_parts.append(f"(内心独白: {interaction.thought})\n")
        messages_text_parts.append("\n")
    messages_text = "".join(messages_text_parts)

    summarize_variables = {
        "CURRENT_CORE_SUMMARY": summary.core_summary,
        "CURRENT_KEY_FACTS": summary.key_facts,
        "MESSAGES_TEXT": messages_text,
    }

    full_summarize_prompt = ""
    if prompt_mgr:
        try:
            full_summarize_prompt = await prompt_mgr.assemble_prompt(
                PromptCategory.SHORT_SUMMARY, summarize_variables,
            )
        except Exception as e:
            logger.error(f"组装 Summarize Prompt 失败 trace_id={trace_id} error={e}")

    from app.api.internal_service import internal_service
    try:
        new_core_summary, new_key_facts = await internal_service.short_summarize(trace_id, full_summarize_prompt)
    except Exception as e:
        logger.error(f"调用 ShortSummarize 失败 trace_id={trace_id} error={e}")
        return

    if not new_core_summary.strip() or not new_key_facts.strip():
        logger.warning(f"返回的摘要存在空字段，放弃本次更新 session_id={session_id}")
        return

    new_summary = ChatSummary(core_summary=new_core_summary, key_facts=new_key_facts)

    try:
        await redis_repo.update_summary_and_trim(session_id, new_summary, compress_count)
        logger.info(f"摘要压缩完成 session_id={session_id} trimmed_count={compress_count}")
    except Exception as e:
        logger.error(f"更新摘要并裁剪历史失败 trace_id={trace_id} error={e}")
