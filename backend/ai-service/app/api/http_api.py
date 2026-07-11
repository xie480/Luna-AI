"""Luna AI HTTP API 服务模块。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.logger import logger
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, Interaction
from app.repository.long_answer_cache import LongAnswerSummaryCache
from app.repository.models import InteractionModel
from app.types.constants import (
    Role,
    WS_MSG_TYPE_CHAT_STREAM,
    WS_MSG_TYPE_EVT_INIT_STATE,
    WS_MSG_TYPE_RES_CALENDAR_METADATA,
    WS_MSG_TYPE_RES_CHAT_HISTORY,
)
from app.user_profile.service import UserProfileService
from app.utils.snowflake import generate_string_id
from app.workflow.constants import ChatMode
from app.workflow.service import ChatWorkflowService

router = APIRouter(prefix="/api", tags=["api"])


class APIResponse(BaseModel):
    type: str
    trace_id: str
    payload: Any


class InteractionQA(BaseModel):
    msgId: str
    userContent: str
    assistantContent: str
    timestamp: int
    hasLongAnswer: bool = False
    longAnswerId: str = ""


class InitStateRequestPayload(BaseModel):
    sessionId: str = ""


class ChatRequestPayload(BaseModel):
    """前端 /api/chat POST 请求体。"""
    sessionId: str
    message: str
    msgId: str
    ttsEnabled: bool = True
    # TTS 语音语言：zh（中文）/ ja（日语），默认为中文
    ttsLanguage: str = "zh"
    # LLM 响应模式：streaming（流式） / unified（统一非流式），默认可由前端传入
    llmResponseMode: str = "unified"
    chatMode: str = "daily_chat"
    answer_mode: str = "short"  # short / long


def get_pg_client():
    from app.main import app
    return app.state.pg_client

async def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    return x_trace_id or generate_string_id()


async def get_pg_repo(request: Request) -> Optional[ChatHistoryPGRepo]:
    return getattr(request.app.state, "pg_repo", None)


async def get_redis_repo(request: Request) -> Optional[ChatHistoryRedisRepo]:
    return getattr(request.app.state, "redis_repo", None)


async def get_chat_workflow_service(request: Request) -> Optional[ChatWorkflowService]:
    return getattr(request.app.state, "chat_workflow_service", None)


@router.get("/calendar", response_model=APIResponse)
async def get_calendar_metadata(
    year_month: str,
    trace_id: str = Depends(get_trace_id),
    pg_repo: Optional[ChatHistoryPGRepo] = Depends(get_pg_repo),
) -> APIResponse:
    if not year_month:
        raise HTTPException(status_code=400, detail="year_month is required")
    active_dates: List[str] = []
    if pg_repo:
        try:
            active_dates = await pg_repo.get_active_dates_by_month(year_month)
        except Exception as exc:
            logger.error(f"获取日历元数据失败 trace_id={trace_id} error={exc}", exc_info=True)
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
    if not date:
        raise HTTPException(status_code=400, detail="date is required")
    interactions: List[InteractionModel] = []
    if pg_repo:
        try:
            interactions = await pg_repo.get_interactions_by_date(date)
        except Exception as exc:
            logger.error(f"获取聊天记录失败 trace_id={trace_id} error={exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="数据库错误")
    messages = []
    for interaction in interactions:
        messages.append(
            {
                "id": interaction.message_id,
                "role": Role.USER.value,
                "content": interaction.user_content,
                "created_at": interaction.created_at.isoformat(),
            }
        )
        assistant_content = interaction.error or interaction.assistant_content
        
        has_long_answer = False
        long_answer_id = ""
        
        metadata = {}
        if interaction.long_answer_id:
            has_long_answer = True
            long_answer_id = interaction.long_answer_id
            metadata["hasLongAnswer"] = True
            metadata["longAnswerId"] = long_answer_id
            
        messages.append(
            {
                "id": interaction.id,
                "role": Role.ASSISTANT.value,
                "content": assistant_content,
                "thought": interaction.thought,
                "emotion": interaction.emotion,
                "created_at": interaction.created_at.isoformat(),
                "metadata": metadata
            }
        )
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
    session_id = payload.sessionId or datetime.now().strftime("%Y%m%d")
    recent_history: List[Interaction] = []
    if redis_repo:
        try:
            _, recent_history = await redis_repo.get_context(session_id)
            # 为最近的历史记录注入 summary
            for item in recent_history:
                msg_id = item.get("msgId", "") if isinstance(item, dict) else getattr(item, "msgId", "")
                if msg_id:
                    summary_data = await LongAnswerSummaryCache.get_summary(session_id, msg_id)
                    if summary_data and "summary" in summary_data:
                        if isinstance(item, dict):
                            item["long_answer_summary"] = summary_data["summary"]
                        else:
                            setattr(item, "long_answer_summary", summary_data["summary"])
        except Exception as exc:
            logger.error(f"从 Redis 获取上下文失败 trace_id={trace_id} error={exc}")
    last_3_history = recent_history[-3:]
    recent_qa = [
        InteractionQA(
            msgId=item.get("msgId", "") if isinstance(item, dict) else getattr(item, "msgId", ""),
            userContent=item.get("userContent", "") if isinstance(item, dict) else getattr(item, "userContent", ""),
            assistantContent=item.get("assistantContent", "") if isinstance(item, dict) else getattr(item, "assistantContent", ""),
            timestamp=item.get("timestamp", 0) if isinstance(item, dict) else getattr(item, "timestamp", 0),
            hasLongAnswer=item.get("hasLongAnswer", False) if isinstance(item, dict) else getattr(item, "hasLongAnswer", False),
            longAnswerId=item.get("longAnswerId", "") if isinstance(item, dict) else getattr(item, "longAnswerId", ""),
        )
        for item in last_3_history
    ]
    return APIResponse(
        type=WS_MSG_TYPE_EVT_INIT_STATE,
        trace_id=trace_id,
        payload={"sessionId": session_id, "recentQA": [qa.model_dump() for qa in recent_qa]},
    )


@router.post("/chat")
async def chat_request(
    payload: ChatRequestPayload,
    trace_id: str = Depends(get_trace_id),
    chat_workflow_service: Optional[ChatWorkflowService] = Depends(get_chat_workflow_service),
) -> APIResponse:
    logger.info(f"收到 /api/chat 请求 trace_id={trace_id} sessionId={payload.sessionId} msgId={payload.msgId}")
    if not payload.sessionId:
        raise HTTPException(status_code=400, detail="sessionId is required")
    if not payload.message:
        raise HTTPException(status_code=400, detail="message is required")
    if not chat_workflow_service:
        logger.error(
            f"[ChatAPI] ChatWorkflowService 不可用，服务可能初始化失败"
            f" trace_id={trace_id} sessionId={payload.sessionId}"
        )
        raise HTTPException(
            status_code=503,
            detail="聊天服务未就绪，请检查后端日志并等待服务重启",
        )
    # 将前端传入的 chatMode 字符串转换为 ChatMode 枚举
    try:
        chat_mode_enum: ChatMode = ChatMode(payload.chatMode)
    except ValueError:
        logger.warning(f"无效的 chatMode 值 '{payload.chatMode}'，降级为默认 daily_chat")
        chat_mode_enum = ChatMode.DAILY_CHAT

    # 将前端传入的 LLM 响应模式透传给工作流服务
    result_payload = await chat_workflow_service.start_daily_chat(
        trace_id=trace_id,
        session_id=payload.sessionId,
        message=payload.message,
        frontend_message_id=payload.msgId,
        tts_enabled=payload.ttsEnabled,
        tts_language=payload.ttsLanguage,
        llm_response_mode=payload.llmResponseMode,
        chat_mode=chat_mode_enum,
        answer_mode=payload.answer_mode,
    )
    return APIResponse(
        type=WS_MSG_TYPE_CHAT_STREAM,
        trace_id=trace_id,
        payload=result_payload,
    )
