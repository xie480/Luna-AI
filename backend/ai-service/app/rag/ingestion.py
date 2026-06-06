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
        """提交本地文件摄入任务。"""
        document_id = generate_string_id()
        task_id = generate_string_id()
        await self.pg_repo.create_document(
            document_id=document_id,
            filename=filename,
            source_type=RagSourceType.LOCAL_FILE,
            status=RagDocumentStatus.PARSING,
        )
        task = asyncio.create_task(
            self._run_file_ingestion(task_id, document_id, filename, content, options, trace_id)
        )
        self._track_task(task)
        return RagIngestionTaskDTO(task_id=task_id, document_id=document_id)

    async def submit_url(self, request: RagUrlIngestionRequest, trace_id: str) -> RagIngestionTaskDTO:
        """提交 URL 摄入任务。"""
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
        """执行清洗后内容的切片、向量化与双库提交。"""
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
        await self.pg_repo.save_chunks(chunks)
        await self.pg_repo.update_document_status(
            document_id=document_id,
            from_status=RagDocumentStatus.PARSING,
            to_status=RagDocumentStatus.EMBEDDING,
            trace_id=trace_id,
            task_id=task_id,
            estimated_tokens=text_tokens,
        )
        vectors = await self._embed_chunks(chunks)
        if self.qdrant_repo is None:
            raise RuntimeError("RAG Qdrant 仓库不可用，无法完成知识向量入库")
        await self.qdrant_repo.upsert_chunks(chunks, vectors)
        await self.pg_repo.update_document_status(
            document_id=document_id,
            from_status=RagDocumentStatus.EMBEDDING,
            to_status=RagDocumentStatus.COMPLETED,
            trace_id=trace_id,
            task_id=task_id,
            estimated_tokens=text_tokens,
        )
        logger.info(
            f"RAG 摄入任务完成 trace_id={trace_id} task_id={task_id} "
            f"document_id={document_id} chunks_count={len(chunks)}"
        )

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
