import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.repository.models import LongAnswerModel
from app.types.constants import LongAnswerStatus
from app.utils.snowflake import generate_string_id

logger = logging.getLogger(__name__)

class LongAnswerPGRepo:
    """
    长回答 PostgreSQL 仓储类。
    处理 long_answers 表的读写操作。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_long_answer(
        self,
        interaction_message_id: str,
        session_id: str,
        user_message_id: Optional[str] = None,
        title: str = "",
        status: str = LongAnswerStatus.PENDING.value,
        answer_type: str = "long_answer",
        source_mode: str = "",
        meta_payload: Optional[Dict[str, Any]] = None,
    ) -> LongAnswerModel:
        """
        创建一条新的长回答记录
        """
        if meta_payload is None:
            meta_payload = {}
            
        long_answer_id = generate_string_id()
        model = LongAnswerModel(
            id=long_answer_id,
            interaction_message_id=interaction_message_id,
            session_id=session_id,
            user_message_id=user_message_id,
            title=title,
            status=status,
            answer_type=answer_type,
            source_mode=source_mode,
            meta_payload=meta_payload,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def get_by_id(self, long_answer_id: str) -> Optional[LongAnswerModel]:
        """
        根据 ID 获取长回答记录
        """
        stmt = select(LongAnswerModel).where(LongAnswerModel.id == long_answer_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_interaction_message_id(self, message_id: str) -> Optional[LongAnswerModel]:
        """
        根据前端的 assistant message_id 获取长回答记录
        """
        stmt = select(LongAnswerModel).where(LongAnswerModel.interaction_message_id == message_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_content(
        self,
        long_answer_id: str,
        content_markdown: str,
        chunk_count: int,
        token_count: int = 0
    ) -> bool:
        """
        更新长回答的正文内容
        """
        stmt = (
            update(LongAnswerModel)
            .where(LongAnswerModel.id == long_answer_id)
            .values(
                content_markdown=content_markdown,
                chunk_count=chunk_count,
                token_count=token_count
            )
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def update_status(
        self,
        long_answer_id: str,
        status: str,
        error_message: str = ""
    ) -> bool:
        """
        更新长回答的状态
        """
        values = {"status": status, "error_message": error_message}
        if status == LongAnswerStatus.COMPLETED.value:
            from sqlalchemy import func
            values["completed_at"] = func.now()

        stmt = (
            update(LongAnswerModel)
            .where(LongAnswerModel.id == long_answer_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def update_summary(
        self,
        long_answer_id: str,
        short_summary: str,
        title: str = ""
    ) -> bool:
        """
        更新长回答的摘要和标题
        """
        values = {"short_summary": short_summary}
        if title:
            values["title"] = title
            
        stmt = (
            update(LongAnswerModel)
            .where(LongAnswerModel.id == long_answer_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def bind_interaction(
        self,
        long_answer_id: str,
        interaction_id: str
    ) -> bool:
        """
        回填 interaction_id
        """
        stmt = (
            update(LongAnswerModel)
            .where(LongAnswerModel.id == long_answer_id)
            .values(interaction_id=interaction_id)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def list_by_session_id(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0
    ) -> List[LongAnswerModel]:
        """
        分页获取指定会话下的长回答记录（按创建时间倒序）
        """
        stmt = (
            select(LongAnswerModel)
            .where(LongAnswerModel.session_id == session_id)
            .order_by(LongAnswerModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
