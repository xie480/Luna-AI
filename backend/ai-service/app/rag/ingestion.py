"""
Luna RAG 摄入服务模块

做什么：编排知识源解析、切片、Embedding、PostgreSQL/Qdrant 双写和状态迁移。
为什么这样做：摄入是有副作用的异步流程，必须由 Python 后端统一控制并保证失败可解释。
输入输出：输入上传文件或 URL 请求，输出 task_id/document_id，后台完成落盘。
边界条件：后台任务带超时；PG 写入成功但 Qdrant 失败时标记 failed 并保留错误日志供重试排查。
异常行为：所有异常写入 rag_documents.error_log，并通过日志记录 trace_id/task_id/document_id。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from app.logger import logger
from app.rag.chunker import ChunkerConfig, build_chunker, estimate_tokens
from app.rag.loaders import CleanDocumentContent, DocumentLoader, UrlContentLoader
from app.rag.types import ChunkUnit, RagIngestionTaskDTO, RagUrlIngestionRequest
from app.repository.rag_pg import RagPGRepository
from app.repository.rag_qdrant import RagQdrantRepository
from app.types.constants import RagChunkStrategy, RagDocumentStatus, RagSourceType
from app.utils.snowflake import generate_string_id


class EmbeddingService(Protocol):
    """Embedding 推理服务协议。"""

    async def get_embedding_vector(self, text: str) -> list[float]:
        """返回文本向量。"""


@dataclass(frozen=True)
class IngestionOptions:
    """摄入切片参数。"""

    strategy: RagChunkStrategy
    chunk_size: int
    overlap: int
    regex_pattern: str | None = None


class RagIngestionService:
    """
    RAG 知识摄入服务。

    做什么：提交异步任务并在后台执行完整摄入管道。
    为什么这样做：上传和网页抓取可能耗时较长，API 必须快速返回 task_id 供前端轮询。
    """

    def __init__(
        self,
        pg_repo: RagPGRepository,
        qdrant_repo: RagQdrantRepository | None,
        inference_svc: EmbeddingService | None,
        task_timeout_seconds: float = 300.0,
    ) -> None:
        self.pg_repo = pg_repo
        self.qdrant_repo = qdrant_repo
        self.inference_svc = inference_svc
        self.task_timeout_seconds = task_timeout_seconds
        self.document_loader = DocumentLoader()
        self.url_loader = UrlContentLoader()
        self._tasks: set[asyncio.Task[None]] = set()

    async def submit_file(
        self,
        filename: str,
        content: bytes,
        options: IngestionOptions,
        trace_id: str,
    ) -> RagIngestionTaskDTO:
        """提交本地文件摄入任务。实现 L1 与 L2 强防重逻辑。"""
        import hashlib
        
        file_hash = hashlib.sha256(content).hexdigest()
        file_size = len(content)
        
        # L1 物理 Hash 防重
        existing_docs = await self.pg_repo.get_document_by_hash(file_hash)
        if existing_docs:
            doc = existing_docs[0]
            raise ValueError(f"文档已存在于知识库中 (DOC_ID: {doc.id})")
            
        # L2 语义防重 (相同文件名且大小差异 < 1%)
        similar_docs = await self.pg_repo.get_documents_by_filename(filename)
        for doc in similar_docs:
            if doc.file_size and abs(doc.file_size - file_size) / float(doc.file_size) < 0.01:
                raise ValueError(f"存在高度相似的文档 (DOC_ID: {doc.id})，请使用更新覆盖代替新增")

        document_id = generate_string_id()
        task_id = generate_string_id()
        await self.pg_repo.create_document(
            document_id=document_id,
            filename=filename,
            source_type=RagSourceType.LOCAL_FILE,
            status=RagDocumentStatus.PARSING,
            file_hash=file_hash,
            file_size=file_size,
        )
        task = asyncio.create_task(
            self._run_file_ingestion(task_id, document_id, filename, content, options, trace_id)
        )
        self._track_task(task)
        return RagIngestionTaskDTO(task_id=task_id, document_id=document_id)

    async def submit_url(self, request: RagUrlIngestionRequest, trace_id: str) -> RagIngestionTaskDTO:
        """提交 URL 摄入任务。由于 URL 内容需抓取后才知晓，初期只依赖 URL 本身做 L2 防重。"""
        
        # L2 语义防重
        similar_docs = await self.pg_repo.get_documents_by_filename(request.url)
        if similar_docs:
            doc = similar_docs[0]
            raise ValueError(f"该网址已存在于知识库中 (DOC_ID: {doc.id})，请使用更新覆盖代替新增")

        document_id = generate_string_id()
        task_id = generate_string_id()
        await self.pg_repo.create_document(
            document_id=document_id,
            filename=request.url,
            source_type=RagSourceType.URL,
            status=RagDocumentStatus.PARSING,
        )
        options = IngestionOptions(
            strategy=request.strategy,
            chunk_size=request.chunk_size,
            overlap=request.overlap,
            regex_pattern=request.regex_pattern,
        )
        task = asyncio.create_task(self._run_url_ingestion(task_id, document_id, request.url, options, trace_id))
        self._track_task(task)
        return RagIngestionTaskDTO(task_id=task_id, document_id=document_id)

    async def shutdown(self) -> None:
        """
        关闭摄入服务。

        做什么：取消仍在运行的后台摄入任务并等待回收。
        为什么这样做：应用退出时不能遗留悬挂协程或半写状态。
        """
        if not self._tasks:
            return
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("RAG 摄入服务后台任务已全部回收")

    def _track_task(self, task: asyncio.Task[None]) -> None:
        """跟踪后台任务生命周期，任务结束后自动移除引用。"""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_file_ingestion(
        self,
        task_id: str,
        document_id: str,
        filename: str,
        content: bytes,
        options: IngestionOptions,
        trace_id: str,
    ) -> None:
        """执行文件摄入后台任务，带超时看门狗。"""
        try:
            await asyncio.wait_for(
                self._ingest_clean_content(
                    task_id,
                    document_id,
                    await self.document_loader.extract_from_bytes(filename, content),
                    options,
                    trace_id,
                ),
                timeout=self.task_timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._mark_failed(document_id, task_id, trace_id, "摄入任务被取消")
            raise
        except Exception as exc:
            await self._mark_failed(document_id, task_id, trace_id, str(exc))

    async def _run_url_ingestion(
        self,
        task_id: str,
        document_id: str,
        url: str,
        options: IngestionOptions,
        trace_id: str,
    ) -> None:
        """执行 URL 摄入后台任务，带超时看门狗。"""
        try:
            clean_content = await self.url_loader.extract(url)
            await asyncio.wait_for(
                self._ingest_clean_content(task_id, document_id, clean_content, options, trace_id),
                timeout=self.task_timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._mark_failed(document_id, task_id, trace_id, "摄入任务被取消")
            raise
        except Exception as exc:
            await self._mark_failed(document_id, task_id, trace_id, str(exc))

    async def _ingest_clean_content(
        self,
        task_id: str,
        document_id: str,
        clean_content: CleanDocumentContent,
        options: IngestionOptions,
        trace_id: str,
    ) -> None:
        """
        执行清洗后内容的切片、向量化与双库提交。
        如果当前文档是更新版本 (有 previous_version_id)，则执行切片级增量更新。
        """
        import hashlib
        from app.infrastructure.qdrant import UpsertPoint
        
        text_tokens = estimate_tokens(clean_content.text)
        config = ChunkerConfig(
            chunk_size=options.chunk_size,
            overlap=options.overlap,
            regex_pattern=options.regex_pattern,
        )
        chunker = build_chunker(options.strategy, config)
        chunks = chunker.chunk(
            document_id=document_id,
            text=clean_content.text,
            metadata={
                "source_type": clean_content.source_type.value,
                "source_ref": clean_content.source_ref,
                "title": clean_content.title,
                "strategy": options.strategy.value,
            },
        )
        
        doc = await self.pg_repo.get_document(document_id)
        if not doc:
            raise ValueError(f"文档不存在: {document_id}")
            
        # 若为更新，URL 可能在这一步才能拿到 Hash
        if not doc.file_hash:
            file_hash = hashlib.sha256(clean_content.text.encode('utf-8')).hexdigest()
            await self.pg_repo.pg_client.session_factory().execute(
                f"UPDATE rag_documents SET file_hash = '{file_hash}' WHERE id = '{document_id}'"
            )

        original_doc_id = doc.previous_version_id
        
        # 1. 保存 Chunk 文本记录
        await self.pg_repo.save_chunks(chunks)
        await self.pg_repo.update_document_status(
            document_id=document_id,
            from_status=RagDocumentStatus.PARSING,
            to_status=RagDocumentStatus.EMBEDDING,
            trace_id=trace_id,
            task_id=task_id,
            estimated_tokens=text_tokens,
        )

        if self.qdrant_repo is None:
            raise RuntimeError("RAG Qdrant 仓库不可用，无法完成知识向量入库")
            
        # 2. 增量比对与向量重用逻辑
        if original_doc_id:
            logger.info(f"触发增量更新逻辑 document_id={document_id} original_doc_id={original_doc_id}")
            old_chunk_map = await self.pg_repo.get_chunk_hash_map(original_doc_id)
            reused_chunks: list[ChunkUnit] = []
            needs_embed_chunks: list[ChunkUnit] = []
            old_to_new_id_map: dict[str, str] = {}
            
            for chunk in chunks:
                if chunk.chunk_hash in old_chunk_map:
                    old_chunk_id = old_chunk_map[chunk.chunk_hash]
                    old_to_new_id_map[old_chunk_id] = chunk.chunk_id
                    reused_chunks.append(chunk)
                else:
                    needs_embed_chunks.append(chunk)
                    
            # 2.1 从 Qdrant 取回可复用旧向量
            old_vectors = await self.qdrant_repo.batch_retrieve_vectors(list(old_to_new_id_map.keys()))
            reused_points: list[UpsertPoint] = []
            for old_cid, new_cid in old_to_new_id_map.items():
                if old_cid in old_vectors:
                    reused_points.append(
                        UpsertPoint(
                            id=int(new_cid),
                            vector=old_vectors[old_cid],
                            payload={"chunk_id": new_cid, "doc_id": document_id}
                        )
                    )
            
            # 2.2 为新增切片计算向量
            new_vectors = await self._embed_chunks(needs_embed_chunks)
            new_points: list[UpsertPoint] = []
            for chunk, vec in zip(needs_embed_chunks, new_vectors):
                new_points.append(
                    UpsertPoint(
                        id=int(chunk.chunk_id),
                        vector=vec,
                        payload={"chunk_id": chunk.chunk_id, "doc_id": document_id}
                    )
                )
            
            # 2.3 批量注入所有切片
            all_points = reused_points + new_points
            await self.qdrant_repo.bulk_upsert(all_points)
            deleted_count = len(old_chunk_map) - len(reused_points)
            logger.info(f"增量更新完成，复用 {len(reused_points)} 个旧切片，新增计算 {len(new_points)} 个切片, 计划清理 {deleted_count} 个过期切片")
        else:
            # 常规全量更新
            vectors = await self._embed_chunks(chunks)
            await self.qdrant_repo.upsert_chunks(chunks, vectors)

        # 3. 原子切换 (Commit) 并处理废弃文档
        async with self.pg_repo.pg_client.session_factory() as session:
            from sqlalchemy import update
            from app.repository.models import RagDocument
            
            # 激活新文档
            stmt_active = update(RagDocument).where(RagDocument.id == document_id).values(
                status=RagDocumentStatus.ACTIVE.value,
                estimated_tokens=text_tokens
            )
            await session.execute(stmt_active)
            
            # 废弃旧文档
            if original_doc_id:
                stmt_deprecate = update(RagDocument).where(RagDocument.id == original_doc_id).values(
                    status=RagDocumentStatus.DEPRECATED.value
                )
                await session.execute(stmt_deprecate)
                
            await session.commit()
            
        if original_doc_id:
            logger.info(
                f"RAG 更新任务完成 trace_id={trace_id} task_id={task_id} "
                f"new_document_id={document_id} original_document_id={original_doc_id} "
                f"reused_chunks={len(reused_points)} new_chunks={len(new_points)} deleted_chunks={deleted_count}"
            )
        else:
            logger.info(
                f"RAG 摄入任务完成 trace_id={trace_id} task_id={task_id} "
                f"document_id={document_id} chunks_count={len(chunks)}"
            )
        
        # 触发清理 Worker 回收旧文档
        if original_doc_id:
            from app.config.event_bus import event_bus
            from app.config.event_bus import RagDocumentDeprecatedEvent
            await event_bus.publish(RagDocumentDeprecatedEvent(doc_id=original_doc_id))

    async def _embed_chunks(self, chunks: list[ChunkUnit]) -> list[list[float]]:
        """串行向量化切片，避免本地 CPU 模型被并发压垮。"""
        if self.inference_svc is None:
            raise RuntimeError("Embedding 推理服务不可用")
        vectors: list[list[float]] = []
        for chunk in chunks:
            vector = await self.inference_svc.get_embedding_vector(chunk.text)
            if not vector:
                raise RuntimeError(f"Embedding 返回空向量 chunk_id={chunk.chunk_id}")
            vectors.append(vector)
        return vectors

    async def _mark_failed(self, document_id: str, task_id: str, trace_id: str, error: str) -> None:
        """将摄入任务标记为失败并写入可追踪错误。"""
        logger.error(
            f"RAG 摄入任务失败 trace_id={trace_id} task_id={task_id} document_id={document_id} error={error}"
        )
        await self.pg_repo.update_document_status(
            document_id=document_id,
            from_status=None,
            to_status=RagDocumentStatus.FAILED,
            trace_id=trace_id,
            task_id=task_id,
            error_log=error,
        )
