"""
Luna AI PostgreSQL 聊天历史记录存储库

做什么：封装 PostgreSQL 长期归档读写。
为什么这样做：为前端聊天记录展示区提供详细的持久化数据。
输入输出：
    - ChatHistoryPGRepo: 聊天历史记录存储库类
边界条件：
    - 按时间降序/升序查询
    - 日期范围查询
异常行为：
    - 数据库操作失败时抛出异常
"""

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgres import PostgresClient
from app.repository.models import InteractionModel


class ChatHistoryPGRepo:
    """封装 PostgreSQL 长期归档读写"""

    def __init__(self, pg_client: PostgresClient):
        self.pg_client = pg_client

    async def save_interaction(self, interaction: InteractionModel) -> None:
        """
        保存单次问答交互记录（一问一答绑定为完整存储单元）到 PostgreSQL
        """
        async with self.pg_client.session() as session:
            session.add(interaction)
            await session.commit()
            return

    async def get_interactions_by_session_id(self, session_id: str, limit: int, offset: int) -> List[InteractionModel]:
        """
        分页查询历史交互记录
        """
        async with self.pg_client.session() as session:
            stmt = (
                select(InteractionModel)
                .where(InteractionModel.session_id == session_id)
                .order_by(InteractionModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_interactions_by_date(self, date_str: str) -> List[InteractionModel]:
        """
        查询指定日期的所有交互记录
        做什么：根据传入的日期（YYYY-MM-DD），查询该日 00:00:00 至 23:59:59 的所有记录，按时间升序排列
        为什么这样做：为前端聊天记录展示区提供详细的持久化数据
        """
        # 解析本地时间的起止时间
        # 注意：在 Python 中，datetime.strptime 默认是不带时区的 (naive)
        # 如果数据库中存储的是带时区的 (timezone=True)，需要确保比较时时区一致
        # 这里我们假设服务器运行在本地时区，或者使用 UTC
        # 为了与 Go 保持一致，我们使用本地时区
        from dateutil import tz
        local_tz = tz.tzlocal()
        
        try:
            start_time = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz)
            end_time = datetime.strptime(f"{date_str} 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz)
        except ValueError as e:
            raise ValueError(f"解析日期失败: {e}")

        async with self.pg_client.session() as session:
            stmt = (
                select(InteractionModel)
                .where(InteractionModel.created_at >= start_time)
                .where(InteractionModel.created_at <= end_time)
                .order_by(InteractionModel.created_at.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_active_dates_by_month(self, year_month: str) -> List[str]:
        """
        聚合查询指定月份中有交互记录的日期列表
        做什么：查询指定月份（YYYY-MM）内，存在交互记录的所有不重复的日期（DD）
        为什么这样做：当 Redis 缓存未命中时，从 PG 重建日历元数据
        """
        from dateutil import tz
        from dateutil.relativedelta import relativedelta
        local_tz = tz.tzlocal()
        
        try:
            start_time = datetime.strptime(f"{year_month}-01 00:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz)
            end_time = start_time + relativedelta(months=1)
        except ValueError as e:
            raise ValueError(f"解析月份时间失败: {e}")

        async with self.pg_client.session() as session:
            stmt = (
                select(InteractionModel.created_at)
                .where(InteractionModel.created_at >= start_time)
                .where(InteractionModel.created_at < end_time)
            )
            result = await session.execute(stmt)
            created_ats = result.scalars().all()
            
            # 在 Python 层面转换为本地时间并提取日期
            date_set = set()
            for t in created_ats:
                # 确保 t 是带时区的，并转换为本地时区
                if t.tzinfo is None:
                    t = t.replace(tzinfo=tz.tzutc())
                local_t = t.astimezone(local_tz)
                date_set.add(local_t.strftime("%d"))
                
            return list(date_set)
