"""
Luna AI PostgreSQL 错误日志存储库

做什么：封装 PostgreSQL 错误日志读写操作，提供前端错误上报的持久化能力。
为什么这样做：前端捕获的异常必须同步写入数据库，实现可追溯的错误审计。
输入输出：
    - ErrorLogPGRepo: 错误日志存储库类
边界条件：
    - 字段名、类型、索引必须与现有数据库完全一致
    - 使用 async/await 异步访问
异常行为：
    - 数据库操作失败时抛出异常
"""

from typing import Optional

from app.infrastructure.postgres import PostgresClient
from app.repository.models import ErrorLog


class ErrorLogPGRepo:
    """封装 PostgreSQL 错误日志持久化读写"""

    def __init__(self, pg_client: PostgresClient):
        """
        初始化错误日志存储库
        :param pg_client: PostgreSQL 客户端实例
        """
        self.pg_client = pg_client

    async def save_error_log(self, error_log: ErrorLog) -> None:
        """
        保存一条错误日志记录到 PostgreSQL

        做什么：将前端上报的错误信息持久化到 error_logs 表。
        为什么这样做：所有异常必须有持久化记录，不能仅存于内存。
        输入：
            - error_log: ErrorLog ORM 模型实例
        异常行为：
            - 数据库写入失败时向上抛出异常，由调用方处理重试或降级
        """
        async for session in self.pg_client.get_session():
            session.add(error_log)
            await session.commit()
            return

    async def get_error_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        source: Optional[str] = None,
    ) -> list[ErrorLog]:
        """
        分页查询错误日志记录

        做什么：按条件查询错误日志列表，供审计面板查阅。
        为什么这样做：支持按级别和来源筛选，方便定位问题。
        输入：
            - limit: 每页数量（默认 100）
            - offset: 偏移量（默认 0）
            - level: 按错误级别过滤（可选）
            - source: 按错误来源过滤（可选）
        输出：ErrorLog 对象列表，按时间降序排列
        """
        from sqlalchemy import select, desc

        query = select(ErrorLog)

        if level:
            query = query.where(ErrorLog.level == level)
        if source:
            query = query.where(ErrorLog.source == source)

        query = query.order_by(desc(ErrorLog.created_at)).limit(limit).offset(offset)

        async for session in self.pg_client.get_session():
            result = await session.execute(query)
            return list(result.scalars().all())
        return []

    async def count_error_logs(
        self,
        level: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """
        统计错误日志总数

        做什么：统计符合条件的错误日志条目数。
        为什么这样做：支持分页查询的总数计算。
        输入：
            - level: 按错误级别过滤（可选）
            - source: 按错误来源过滤（可选）
        输出：符合条件的记录总数
        """
        from sqlalchemy import select, func

        query = select(func.count(ErrorLog.id))

        if level:
            query = query.where(ErrorLog.level == level)
        if source:
            query = query.where(ErrorLog.source == source)

        async for session in self.pg_client.get_session():
            result = await session.execute(query)
            return result.scalar() or 0
        return 0
