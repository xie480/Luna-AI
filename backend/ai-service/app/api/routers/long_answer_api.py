import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Any, List, Optional
from pydantic import BaseModel

from app.logger import logger
from app.repository.long_answer_pg import LongAnswerPGRepo
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/long_answers", tags=["long_answers"])

class LongAnswerResponse(BaseModel):
    id: str
    interaction_id: Optional[str]
    interaction_message_id: str
    session_id: str
    user_message_id: Optional[str]
    title: str
    content_markdown: str
    short_summary: str
    status: str
    answer_type: str
    source_mode: str
    token_count: int
    chunk_count: int
    error_message: str
    created_at: str
    completed_at: Optional[str]

class LongAnswerListResponse(BaseModel):
    items: List[LongAnswerResponse]
    total: int

async def get_long_answer_repo(request: Request) -> LongAnswerPGRepo:
    # 获取 db session
    pg_client = request.app.state.pg_client
    async with pg_client.session() as session:
        yield LongAnswerPGRepo(session)


@router.get("/{long_answer_id}", response_model=LongAnswerResponse)
async def get_long_answer(
    long_answer_id: str,
    repo: LongAnswerPGRepo = Depends(get_long_answer_repo)
):
    """根据 ID 获取长回答详细内容"""
    try:
        record = await repo.get_by_id(long_answer_id)
        if not record:
            raise HTTPException(status_code=404, detail="Long answer not found")
            
        return LongAnswerResponse(
            id=record.id,
            interaction_id=record.interaction_id,
            interaction_message_id=record.interaction_message_id,
            session_id=record.session_id,
            user_message_id=record.user_message_id,
            title=record.title,
            content_markdown=record.content_markdown,
            short_summary=record.short_summary,
            status=record.status,
            answer_type=record.answer_type,
            source_mode=record.source_mode,
            token_count=record.token_count,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
            created_at=record.created_at.isoformat() if record.created_at else "",
            completed_at=record.completed_at.isoformat() if record.completed_at else None,
        )
    finally:
        await repo.session.close()

@router.get("/by_message/{message_id}", response_model=LongAnswerResponse)
async def get_long_answer_by_message(
    message_id: str,
    repo: LongAnswerPGRepo = Depends(get_long_answer_repo)
):
    """根据 assistant message_id 获取对应的长回答"""
    try:
        record = await repo.get_by_interaction_message_id(message_id)
        if not record:
            raise HTTPException(status_code=404, detail="Long answer not found for message")
            
        return LongAnswerResponse(
            id=record.id,
            interaction_id=record.interaction_id,
            interaction_message_id=record.interaction_message_id,
            session_id=record.session_id,
            user_message_id=record.user_message_id,
            title=record.title,
            content_markdown=record.content_markdown,
            short_summary=record.short_summary,
            status=record.status,
            answer_type=record.answer_type,
            source_mode=record.source_mode,
            token_count=record.token_count,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
            created_at=record.created_at.isoformat() if record.created_at else "",
            completed_at=record.completed_at.isoformat() if record.completed_at else None,
        )
    finally:
        await repo.session.close()
