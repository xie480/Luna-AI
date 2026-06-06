"""
Luna AI PostgreSQL 长期记忆存储库

做什么：封装 PostgreSQL 中长期记忆的读写操作。
为什么这样做：PostgreSQL 是长期记忆的 Single Source of Truth，所有记忆写入必须经过事务控制。
输入输出：
    - LongTermMemoryPGRepo: 长期记忆存储库类
边界条件：
    - 软删除机制
    - 按月查询
异常行为：
    - 数据库操作失败时抛出异常
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.models import LongTermMemory, MemoryStatus


class LongTermMemoryPGRepo:
    """封装 PostgreSQL 中长期记忆的读写操作"""

    def __init__(self, pg_client: PostgresClient):
        self.pg_client = pg_client

    async def save(self, memory: LongTermMemory) -> None:
        """
        保存一条长期记忆记录
        边界条件：
          - memory.status 默认为 MemoryStatus.ACTIVE.value
        """
        if not memory.status:
            memory.status = MemoryStatus.ACTIVE.value

        async for session in self.pg_client.get_session():
            session.add(memory)
            await session.commit()
            logger.info(f"长期记忆记录已保存 session_id={memory.session_id} id={memory.id}")
            return

    async def get_by_session_id(self, session_id: str) -> Optional[LongTermMemory]:
        """
        根据会话 ID 获取长期记忆记录
        """
        async with self.pg_client.session_factory() as session:
            stmt = (
                select(LongTermMemory)
                .where(LongTermMemory.session_id == session_id)
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
            )
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_by_ids(self, ids: List[str]) -> List[LongTermMemory]:
        """
        根据 ID 列表批量获取长期记忆记录
        边界条件：仅返回 status=MemoryStatus.ACTIVE.value 的记录
        """
        if not ids:
            return []

        async with self.pg_client.session_factory() as session:
            stmt = (
                select(LongTermMemory)
                .where(LongTermMemory.id.in_(ids))
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def soft_delete(self, id: str) -> None:
        """
        软删除指定的长期记忆记录
        """
        async for session in self.pg_client.get_session():
            stmt = (
                update(LongTermMemory)
                .where(LongTermMemory.id == id)
                .values(status=MemoryStatus.DELETED.value)
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"长期记忆记录已软删除 id={id}")
            return

    async def list_by_month(self, year_month: str) -> List[LongTermMemory]:
        """
        按月查询长期记忆记录列表
        用例：前端日历面板按月加载历史记忆概览
        """
        from dateutil import tz
        from dateutil.relativedelta import relativedelta
        local_tz = tz.tzlocal()
        
        try:
            start_time = datetime.strptime(f"{year_month}-01 00:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz)
            end_time = start_time + relativedelta(months=1)
        except ValueError as e:
            raise ValueError(f"解析月份时间失败: {e}")

        async with self.pg_client.session_factory() as session:
            stmt = (
                select(LongTermMemory)
                .where(LongTermMemory.created_at >= start_time)
                .where(LongTermMemory.created_at < end_time)
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
                .order_by(LongTermMemory.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_all_active_session_ids(self) -> List[str]:
        """
        获取所有活跃的长期记忆会话 ID 列表
        用途：启动时兜底检测用，判断哪些历史会话已有长期记忆记录
        """
        async with self.pg_client.session_factory() as session:
            stmt = (
                select(LongTermMemory.session_id)
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_by_session_id(self, session_id: str) -> None:
        """
        删除指定会话的所有长期记忆记录
        用途：记忆撤销或重置时清理指定会话的记忆
        """
        async with self.pg_client.session_factory() as session:
            stmt = select(LongTermMemory).where(LongTermMemory.session_id == session_id)
            result = await session.execute(stmt)
            memories = result.scalars().all()
            for memory in memories:
                await session.delete(memory)
            await session.commit()
            logger.info(f"会话长期记忆记录已删除 session_id={session_id}")

    async def get_paginated(self, page: int, page_size: int) -> tuple[List[LongTermMemory], int]:
        """
        分页获取长期记忆记录
        返回: (记录列表, 总条数)
        """
        from sqlalchemy import func
        
        async with self.pg_client.session_factory() as session:
            # 获取总条数
            count_stmt = select(func.count()).select_from(LongTermMemory).where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
            total_count = await session.scalar(count_stmt)
            
            # 获取分页数据
            offset = (page - 1) * page_size
            stmt = (
                select(LongTermMemory)
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
                .order_by(LongTermMemory.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            
            return records, total_count or 0

    async def update_summary(self, id: str, new_summary: str) -> None:
        """
        更新指定 ID 的记忆摘要
        """
        async with self.pg_client.session_factory() as session:
            stmt = (
                update(LongTermMemory)
                .where(LongTermMemory.id == id)
                .values(summary=new_summary)
            )
            await session.execute(stmt)
            await session.commit()
            logger.info(f"长期记忆摘要已更新 id={id}")

    async def search_by_text(self, query_text: str, top_k: int) -> List[LongTermMemory]:
        """
        使用 PostgreSQL 内建全文检索（FTS）执行 BM25 风格的文本搜索

        做什么：对 summary 字段执行 to_tsvector('simple', summary) 向量化，
                将用户查询转为 tsquery 后进行 ts_rank 排序，返回得分最高的 top_k 条。
        为什么这样做：PostgreSQL 的 ts_rank 实现基于标准的 BM25 变体，
                     配合 GIN 索引可支持中等规模文本的高效稀疏检索。
                     对中文采用 simple 配置（单字符粒度），与内存 BM25 的分词策略一致。

        边界条件：
            - 仅返回 status=MemoryStatus.ACTIVE.value 的记录
            - 查询文本为空时返回空列表
            - 检索结果按 ts_rank 得分降序排列
        """
        from sqlalchemy import text

        if not query_text or not query_text.strip():
            return []

        # 使用原始 SQL 执行 PostgreSQL FTS 以利用 to_tsvector/to_tsquery/ts_rank
        # 注意：对中文文本，simple 配置会将每个汉字作为独立 token 处理
        # 这与原内存在 BM25 的中文单字粒度分词策略一致
        sql = text("""
            SELECT id, session_id, summary, status, created_at, updated_at,
                   ts_rank(to_tsvector('simple', summary), plainto_tsquery('simple', :query)) AS rank
            FROM long_term_memories
            WHERE status = :status
              AND to_tsvector('simple', summary) @@ plainto_tsquery('simple', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)

        async with self.pg_client.session_factory() as session:
            try:
                result = await session.execute(sql, {
                    "query": query_text,
                    "status": MemoryStatus.ACTIVE.value,
                    "limit": top_k,
                })
                rows = result.all()
                memories = []
                for row in rows:
                    memory = LongTermMemory(
                        id=row[0],
                        session_id=row[1],
                        summary=row[2],
                        status=row[3],
                        created_at=row[4],
                        updated_at=row[5],
                    )
                    memories.append(memory)
                logger.info(f"PG FTS 检索完成 hits={len(memories)} top_k={top_k} query=\"{query_text[:50]}...\"")
                return memories
            except Exception as e:
                logger.error(f"PG FTS 检索失败 query=\"{query_text[:50]}...\" error={e}")
                # 如果 FTS 失败（例如未安装扩展），降级返回空
                return []

    async def create_fts_index(self) -> None:
        """
        为 long_term_memories.summary 创建 GIN 索引以加速 FTS 检索

        做什么：创建索引 idx_ltm_summary_fts ON long_term_memories
                USING GIN (to_tsvector('simple', summary))
        为什么这样做：GIN 索引可将 ts_rank 排序效率提升两个数量级，
                     是生产环境中 FTS 检索的必备条件。
        边界条件：
            - IF NOT EXISTS 确保幂等性
            - 仅在首次部署或迁移时调用
        """
        from sqlalchemy import text
        sql = text("""
            CREATE INDEX IF NOT EXISTS idx_ltm_summary_fts
            ON long_term_memories
            USING GIN (to_tsvector('simple', summary))
        """)
        async with self.pg_client.session_factory() as session:
            try:
                await session.execute(sql)
                await session.commit()
                logger.info("PG FTS GIN 索引创建/确认完成 idx_ltm_summary_fts")
            except Exception as e:
                logger.warning(f"创建 PG FTS GIN 索引失败（不影响核心功能） error={e}")

    async def get_all_active_summaries(self) -> List[tuple[str, str, str]]:
        """
        获取所有活跃长期记忆的 (id, summary, created_at) 元组列表
        用途：为旧版内存 BM25 提供全量语料库（保留向后兼容）。
        边界条件：仅返回 status=MemoryStatus.ACTIVE.value 的记录。
        """
        async with self.pg_client.session_factory() as session:
            stmt = (
                select(LongTermMemory.id, LongTermMemory.summary, LongTermMemory.created_at)
                .where(LongTermMemory.status == MemoryStatus.ACTIVE.value)
            )
            result = await session.execute(stmt)
            rows = result.all()
            # 将 datetime 转为 ISO 格式字符串
            return [(row[0], row[1], row[2].isoformat() if row[2] else "") for row in rows]

    async def delete_hard(self, id: str) -> None:
        """
        硬删除指定的长期记忆记录
        """
        async with self.pg_client.session_factory() as session:
            stmt = select(LongTermMemory).where(LongTermMemory.id == id)
            result = await session.execute(stmt)
            memory = result.scalars().first()
            if memory:
                await session.delete(memory)
                await session.commit()
                logger.info(f"长期记忆记录已硬删除 id={id}")
