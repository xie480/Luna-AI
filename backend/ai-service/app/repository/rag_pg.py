"""
Luna RAG PostgreSQL 知识库仓库

做什么：封装 rag_documents 与 rag_chunks 的注册、状态迁移、文本回表、BM25 检索和父子级联查询。
为什么这样做：PostgreSQL 是知识库文档与切片正文的唯一事实来源，Qdrant 只保存轻量映射。
输入输出：输入 ORM 模型或 ChunkUnit，输出文档、切片与检索候选。
边界条件：状态迁移显式记录日志；所有查询只读取已完成文档的切片。
异常行为：数据库异常向上抛出，由服务层写入 failed 状态并返回明确错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update

from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.rag.types import ChunkUnit
from app.repository.models import RagChunk, RagDocument
from app.types.constants import RagDocumentStatus, RagSourceType


@dataclass(frozen=True)
class RagChunkCandidate:
    """PostgreSQL 检索候选结构。"""

    chunk: RagChunk
    document: RagDocument
    score: float


class RagPGRepository:
    """
    RAG PostgreSQL 仓库。

    做什么：提供文档元数据、切片正文和稀疏检索相关操作。
    为什么这样做：集中保证 SQL 条件、状态过滤和父子查询一致。
    """

    def __init__(self, pg_client: PostgresClient):
        self.pg_client = pg_client

    async def create_document(
        self,
        document_id: str,
        filename: str,
        source_type: RagSourceType,
        status: RagDocumentStatus,
        estimated_tokens: int = 0,
    ) -> RagDocument:
        """注册知识库文档并写入初始状态。"""
        document = RagDocument(
            id=document_id,
            filename=filename,
            source_type=source_type.value,
            status=status.value,
            estimated_tokens=estimated_tokens,
            error_log=None,
        )
        async with self.pg_client.session_factory() as session:
            session.add(document)
            await session.commit()
        logger.info(f"RAG 文档已注册 document_id={document_id} filename={filename} status={status.value}")
        return document

    async def update_document_status(
        self,
        document_id: str,
        from_status: RagDocumentStatus | None,
        to_status: RagDocumentStatus,
        trace_id: str,
        task_id: str,
        error_log: str | None = None,
        estimated_tokens: int | None = None,
    ) -> None:
        """显式迁移文档状态并记录 from -> to。"""
        values: dict[str, Any] = {"status": to_status.value, "error_log": error_log}
        if estimated_tokens is not None:
            values["estimated_tokens"] = estimated_tokens
        async with self.pg_client.session_factory() as session:
            stmt = update(RagDocument).where(RagDocument.id == document_id).values(**values)
            await session.execute(stmt)
            await session.commit()
        from_value = from_status.value if from_status else "unknown"
        logger.info(
            f"RAG 文档状态迁移 from={from_value} to={to_status.value} "
            f"trace_id={trace_id} task_id={task_id} document_id={document_id}"
        )

    async def save_chunks(self, chunks: list[ChunkUnit]) -> None:
        """批量保存知识切片正文到 PostgreSQL。"""
        if not chunks:
            raise ValueError("知识切片列表不能为空")
        models = [
            RagChunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.document_id,
                parent_id=chunk.parent_id,
                content_text=chunk.text,
                meta_payload=chunk.metadata,
            )
            for chunk in chunks
        ]
        async with self.pg_client.session_factory() as session:
            session.add_all(models)
            await session.commit()
        logger.info(f"RAG 知识切片已保存 chunks_count={len(chunks)} document_id={chunks[0].document_id}")

    async def get_document(self, document_id: str) -> RagDocument | None:
        """根据 document_id 获取文档。"""
        async with self.pg_client.session_factory() as session:
            result = await session.execute(select(RagDocument).where(RagDocument.id == document_id))
            return result.scalars().first()

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[RagChunkCandidate]:
        """按 chunk_id 批量回表获取切片正文与文档元数据。"""
        if not chunk_ids:
            return []
        async with self.pg_client.session_factory() as session:
            stmt = (
                select(RagChunk, RagDocument)
                .join(RagDocument, RagDocument.id == RagChunk.doc_id)
                .where(RagChunk.chunk_id.in_(chunk_ids))
                .where(RagDocument.status == RagDocumentStatus.COMPLETED.value)
            )
            result = await session.execute(stmt)
            rows = result.all()
        order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        candidates = [RagChunkCandidate(chunk=row[0], document=row[1], score=0.0) for row in rows]
        candidates.sort(key=lambda item: order.get(item.chunk.chunk_id, len(order)))
        return candidates

    async def get_parent_chunks(self, parent_ids: list[str]) -> dict[str, RagChunk]:
        """按 parent_id 回查父块正文，实现 Small-to-Big 检索扩展。"""
        if not parent_ids:
            return {}
        async with self.pg_client.session_factory() as session:
            stmt = select(RagChunk).where(RagChunk.chunk_id.in_(parent_ids))
            result = await session.execute(stmt)
            chunks = list(result.scalars().all())
        return {chunk.chunk_id: chunk for chunk in chunks}

    async def search_by_text(self, query_text: str, top_k: int) -> list[RagChunkCandidate]:
        """
        使用 PostgreSQL FTS 执行 BM25 风格稀疏检索。

        边界条件：空查询返回空列表；只检索 completed 文档。
        """
        if not query_text.strip():
            return []
        sql = text(
            """
            SELECT c.chunk_id, c.doc_id, c.parent_id, c.content_text, c.meta_payload, c.created_at,
                   d.id, d.filename, d.source_type, d.status, d.estimated_tokens, d.error_log, d.created_at,
                   ts_rank(to_tsvector('simple', c.content_text), plainto_tsquery('simple', :query)) AS rank
            FROM rag_chunks c
            JOIN rag_documents d ON d.id = c.doc_id
            WHERE d.status = :status
              AND to_tsvector('simple', c.content_text) @@ plainto_tsquery('simple', :query)
            ORDER BY rank DESC
            LIMIT :limit
            """
        )
        async with self.pg_client.session_factory() as session:
            result = await session.execute(
                sql,
                {"query": query_text, "status": RagDocumentStatus.COMPLETED.value, "limit": top_k},
            )
            rows = result.all()
        candidates: list[RagChunkCandidate] = []
        for row in rows:
            chunk = RagChunk(
                chunk_id=row[0],
                doc_id=row[1],
                parent_id=row[2],
                content_text=row[3],
                meta_payload=row[4] or {},
                created_at=row[5],
            )
            document = RagDocument(
                id=row[6],
                filename=row[7],
                source_type=row[8],
                status=row[9],
                estimated_tokens=row[10],
                error_log=row[11],
                created_at=row[12],
            )
            candidates.append(RagChunkCandidate(chunk=chunk, document=document, score=float(row[13] or 0.0)))
        logger.info(f"RAG PG FTS 检索完成 hits={len(candidates)} top_k={top_k}")
        return candidates

    async def search_by_time_range(
        self, date_start: str, date_end: str, top_k: int
    ) -> list[RagChunkCandidate]:
        """
        按 created_at 时间范围检索切片候选。

        用于纯时间维度的召回路径，返回的 score 默认设为 0.0。
        """
        sql = text(
            """
            SELECT c.chunk_id, c.doc_id, c.parent_id, c.content_text, c.meta_payload, c.created_at,
                   d.id, d.filename, d.source_type, d.status, d.estimated_tokens, d.error_log, d.created_at,
                   0.0 AS rank
            FROM rag_chunks c
            JOIN rag_documents d ON d.id = c.doc_id
            WHERE d.status = :status
              AND c.created_at >= :date_start
              AND c.created_at <= :date_end
            ORDER BY c.created_at DESC
            LIMIT :limit
            """
        )
        async with self.pg_client.session_factory() as session:
            result = await session.execute(
                sql,
                {
                    "status": RagDocumentStatus.COMPLETED.value,
                    "date_start": date_start,
                    "date_end": date_end,
                    "limit": top_k,
                },
            )
            rows = result.all()
        candidates: list[RagChunkCandidate] = []
        for row in rows:
            chunk = RagChunk(
                chunk_id=row[0],
                doc_id=row[1],
                parent_id=row[2],
                content_text=row[3],
                meta_payload=row[4] or {},
                created_at=row[5],
            )
            document = RagDocument(
                id=row[6],
                filename=row[7],
                source_type=row[8],
                status=row[9],
                estimated_tokens=row[10],
                error_log=row[11],
                created_at=row[12],
            )
            candidates.append(RagChunkCandidate(chunk=chunk, document=document, score=0.0))
        logger.info(f"RAG PG 按时间范围检索完成 hits={len(candidates)} start={date_start} end={date_end}")
        return candidates

    async def create_indexes(self) -> None:
        """创建 RAG 生产索引，幂等执行。"""
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks(doc_id)",
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent_id ON rag_chunks(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag_documents(status)",
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_fts ON rag_chunks USING GIN (to_tsvector('simple', content_text))",
        ]
        async with self.pg_client.session_factory() as session:
            for statement in statements:
                await session.execute(text(statement))
            await session.commit()
        logger.info("RAG PostgreSQL 索引创建或确认完成")

    async def delete_document(self, document_id: str) -> list[str]:
        """删除文档与切片正文，并返回被删除的 chunk_id 列表供 Qdrant 清理。"""
        async with self.pg_client.session_factory() as session:
            result = await session.execute(select(RagChunk.chunk_id).where(RagChunk.doc_id == document_id))
            chunk_ids = list(result.scalars().all())
            await session.execute(delete(RagDocument).where(RagDocument.id == document_id))
            await session.commit()
        logger.info(f"RAG 文档已删除 document_id={document_id} chunks_count={len(chunk_ids)}")
        return chunk_ids

    async def list_documents(self, limit: int = 100) -> list[RagDocument]:
        """列出最近知识库文档。"""
        async with self.pg_client.session_factory() as session:
            stmt = select(RagDocument).order_by(RagDocument.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())
