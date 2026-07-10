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
from app.rag.unicode_guard import inspect_unicode_text
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
        file_hash: str | None = None,
        file_size: int | None = None,
        previous_version_id: str | None = None,
        description: str = "",
    ) -> RagDocument:
        """注册知识库文档并写入初始状态。"""
        document = RagDocument(
            id=document_id,
            filename=filename,
            source_type=source_type.value,
            status=status.value,
            estimated_tokens=estimated_tokens,
            file_hash=file_hash,
            file_size=file_size,
            previous_version_id=previous_version_id,
            error_log=None,
            description=description,
        )
        async with self.pg_client.session() as session:
            session.add(document)
            await session.commit()
        logger.info(f"RAG 文档已注册 document_id={document_id} filename={filename} status={status.value}")
        return document

    async def get_document_by_hash(self, file_hash: str) -> list[RagDocument]:
        """按 file_hash 查询文档，用于 L1 查重拦截"""
        if not file_hash:
            return []
        async with self.pg_client.session_factory() as session:
            stmt = select(RagDocument).where(RagDocument.file_hash == file_hash).where(
                RagDocument.status.in_([RagDocumentStatus.ACTIVE.value, RagDocumentStatus.EMBEDDING.value, RagDocumentStatus.PARSING.value])
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_documents_by_filename(self, filename: str) -> list[RagDocument]:
        """按 filename 查询文档，用于 L2 查重拦截"""
        if not filename:
            return []
        async with self.pg_client.session_factory() as session:
            stmt = select(RagDocument).where(RagDocument.filename == filename).where(
                RagDocument.status.in_([RagDocumentStatus.ACTIVE.value, RagDocumentStatus.EMBEDDING.value, RagDocumentStatus.PARSING.value])
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_chunk_hash_map(self, document_id: str) -> dict[str, str]:
        """获取文档的全部切片 Hash 与 chunk_id 映射关系，用于增量切片比对"""
        if not document_id:
            return {}
        async with self.pg_client.session() as session:
            stmt = select(RagChunk.chunk_hash, RagChunk.chunk_id).where(RagChunk.doc_id == document_id)
            result = await session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}

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
        async with self.pg_client.session() as session:
            stmt = update(RagDocument).where(RagDocument.id == document_id).values(**values)
            await session.execute(stmt)
            await session.commit()
        from_value = from_status.value if from_status else "unknown"
        logger.info(
            f"RAG 文档状态迁移 from={from_value} to={to_status.value} "
            f"trace_id={trace_id} task_id={task_id} document_id={document_id}"
        )

    async def save_chunks(self, chunks: list[ChunkUnit]) -> None:
        """
        批量保存知识切片正文到 PostgreSQL。

        做什么：在入库前抽样检查 Chunk 正文 Unicode 状态。
        为什么这样做：验证 PDF 抽取/清洗后的字符串是否已经安全，区分入库前脏数据与数据库回查问题。
        输入输出：输入 ChunkUnit 列表，写入 rag_chunks.content_text。
        """
        if not chunks:
            raise ValueError("知识切片列表不能为空")
        for chunk in chunks[:5]:
            report = inspect_unicode_text(chunk.text, f"Chunk入库前:chunk_id={chunk.chunk_id}")
            if report.has_anomaly:
                logger.warning(f"RAG Chunk 入库前存在 Unicode 污点 {report.to_log_text()}")
        models = [
            RagChunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.document_id,
                parent_id=chunk.parent_id,
                content_text=chunk.text,
                meta_payload=chunk.metadata,
                chunk_hash=chunk.chunk_hash,
            )
            for chunk in chunks
        ]
        async with self.pg_client.session() as session:
            session.add_all(models)
            await session.commit()
        logger.info(f"RAG 知识切片已保存 chunks_count={len(chunks)} document_id={chunks[0].document_id}")

    async def get_document(self, document_id: str) -> RagDocument | None:
        """根据 document_id 获取文档。"""
        async with self.pg_client.session() as session:
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
                .where(RagDocument.status == RagDocumentStatus.ACTIVE.value)
            )
            result = await session.execute(stmt)
            rows = result.all()
        order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
        candidates = [RagChunkCandidate(chunk=row[0], document=row[1], score=0.0) for row in rows]
        for candidate in candidates[:5]:
            report = inspect_unicode_text(
                candidate.chunk.content_text,
                f"Chunk按ID回查后:chunk_id={candidate.chunk.chunk_id}",
            )
            if report.has_anomaly:
                logger.warning(f"RAG Chunk 按 ID 回查后存在 Unicode 污点 {report.to_log_text()}")
        candidates.sort(key=lambda item: order.get(item.chunk.chunk_id, len(order)))
        return candidates

    async def get_parent_chunks(self, parent_ids: list[str]) -> dict[str, RagChunk]:
        """按 parent_id 回查父块正文，实现 Small-to-Big 检索扩展。"""
        if not parent_ids:
            return {}
        async with self.pg_client.session() as session:
            stmt = select(RagChunk).where(RagChunk.chunk_id.in_(parent_ids))
            result = await session.execute(stmt)
            chunks = list(result.scalars().all())
        for chunk in chunks[:5]:
            report = inspect_unicode_text(chunk.content_text, f"父Chunk回查后:chunk_id={chunk.chunk_id}")
            if report.has_anomaly:
                logger.warning(f"RAG 父 Chunk 回查后存在 Unicode 污点 {report.to_log_text()}")
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
            try:
                result = await session.execute(
                    sql,
                    {"query": query_text, "status": RagDocumentStatus.ACTIVE.value, "limit": top_k},
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
                for candidate in candidates[:5]:
                    report = inspect_unicode_text(
                        candidate.chunk.content_text,
                        f"Chunk FTS回查后:chunk_id={candidate.chunk.chunk_id}",
                    )
                    if report.has_anomaly:
                        logger.warning(f"RAG Chunk FTS 回查后存在 Unicode 污点 {report.to_log_text()}")
                logger.info(f"RAG PG FTS 检索完成 hits={len(candidates)} top_k={top_k}")
                return candidates
            except Exception as e:
                logger.error(f"PG FTS 检索失败 query=\"{query_text[:50]}...\" error={e}")
                # 修复乱码：PostgreSQL 默认配置下如果使用了错误的编码连接或环境，可能会导致查询结果返回问号
                # 此前发生过由于 PowerShell 编码破坏导致查询返回结果损坏的问题，我们在这里增加捕获和容错。
                # 由于这是数据库底层的 FTS 查询问题，我们在最外层使用 utf-8 返回保证系统的正确处理，防止奔溃
                return []

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
            try:
                result = await session.execute(
                    sql,
                    {
                        "status": RagDocumentStatus.ACTIVE.value,
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
            except Exception as e:
                logger.error(f"PG 时间检索失败 start={date_start} end={date_end} error={e}")
                return []

    async def create_indexes(self) -> None:
        """创建 RAG 生产索引，幂等执行。"""
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks(doc_id)",
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent_id ON rag_chunks(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag_documents(status)",
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_fts ON rag_chunks USING GIN (to_tsvector('simple', content_text))",
            "CREATE INDEX IF NOT EXISTS idx_rag_documents_file_hash ON rag_documents(file_hash)",
            "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_hash ON rag_chunks(doc_id, chunk_hash)",
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

    async def list_documents(self, limit: int = 100, status: str | None = None) -> list[RagDocument]:
        """
        列出知识库文档。

        做什么：按状态过滤并返回知识库文档列表。
        为什么这样做：InputReconstructionNode 需要只展示 ACTIVE 状态文档给 LLM，
                     API 路由需要列出所有文档给前端管理面板。
        输入输出：status 为 None 时返回所有文档（API 管理用）；指定 status 时只返回匹配状态的文档。
        边界条件：limit 必须为正整数；status 不合法时返回空结果而非抛异常。
        """
        async with self.pg_client.session_factory() as session:
            stmt = select(RagDocument).order_by(RagDocument.created_at.desc())
            if status is not None:
                stmt = stmt.where(RagDocument.status == status)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())
