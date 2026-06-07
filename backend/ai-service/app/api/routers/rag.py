"""
Luna RAG FastAPI 路由模块

做什么：提供 Phase 7 知识库上传、URL 摄入、切片预览、检索与文档查询 API。
为什么这样做：所有知识库能力必须经 Python API 网关进入，前端只负责展示和交互。
输入输出：统一使用 ResponseModel，所有跨层响应包含 schema_version 与 trace_id。
边界条件：预览接口带 asyncio 看门狗，上传接口立即返回 task_id，不等待耗时摄入。
异常行为：参数或依赖错误返回明确错误码，内部异常记录中文日志。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile

from app.logger import logger
from app.rag.chunker import ChunkerConfig, build_chunker
from app.rag.ingestion import IngestionOptions, RagIngestionService
from app.rag.retrieval import RagRetrievalOrchestrator
from app.rag.types import (
    ChunkPreviewRequest,
    ChunkPreviewResponse,
    RagDocumentDTO,
    RagSearchRequest,
    RagUrlIngestionRequest,
    ChunkUnit,
)
from app.repository.rag_pg import RagPGRepository
from app.types.constants import RagChunkStrategy, RagSourceType, RagDocumentStatus
from app.types.errors import ErrorCode, ResponseModel, create_error_response, create_success_response
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


async def get_trace_id(x_trace_id: str | None = Header(None)) -> str:
    """从请求头获取 TraceID，缺失时使用 Snowflake 生成。"""
    return x_trace_id or generate_string_id()


async def get_ingestion_service(request: Request) -> RagIngestionService:
    """从 app.state 获取 RAG 摄入服务。"""
    service = getattr(request.app.state, "rag_ingestion_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="RAG 摄入服务未初始化")
    return service


async def get_retrieval_orchestrator(request: Request) -> RagRetrievalOrchestrator:
    """从 app.state 获取 RAG 检索编排器。"""
    orchestrator = getattr(request.app.state, "rag_retrieval_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="RAG 检索服务未初始化")
    return orchestrator


async def get_rag_pg_repo(request: Request) -> RagPGRepository:
    """从 app.state 获取 RAG PG 仓库。"""
    repo = getattr(request.app.state, "rag_pg_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="RAG PostgreSQL 仓库未初始化")
    return repo


@router.post("/knowledge/upload", response_model=ResponseModel)
async def upload_knowledge_file(
    file: Annotated[UploadFile, File(...)],
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[RagIngestionService, Depends(get_ingestion_service)],
    strategy: Annotated[RagChunkStrategy, Form()] = RagChunkStrategy.STRUCTURED_AST,
    chunk_size: Annotated[int, Form(ge=80, le=2000)] = 500,
    overlap: Annotated[int, Form(ge=0, le=500)] = 50,
    regex_pattern: Annotated[str | None, Form(max_length=500)] = None,
) -> ResponseModel:
    """提交本地知识文件异步摄入任务。支持拦截重复上传。"""
    if not file.filename:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "文件名不能为空", trace_id)
    content = await file.read()
    if not content:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "上传文件内容不能为空", trace_id)
    try:
        result = await service.submit_file(
            filename=file.filename,
            content=content,
            options=IngestionOptions(strategy=strategy, chunk_size=chunk_size, overlap=overlap, regex_pattern=regex_pattern),
            trace_id=trace_id,
        )
        return create_success_response(result.model_dump(), trace_id)
    except ValueError as exc:
        # 特别捕获防重产生的 ValueError，不以严重错误级打日志
        logger.warning(f"RAG 知识入库拦截 trace_id={trace_id} reason={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)
    except Exception as exc:
        logger.error(f"提交 RAG 文件摄入失败 trace_id={trace_id} filename={file.filename} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)


@router.post("/knowledge/url", response_model=ResponseModel)
async def ingest_knowledge_url(
    payload: RagUrlIngestionRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[RagIngestionService, Depends(get_ingestion_service)],
) -> ResponseModel:
    """提交 URL 知识异步摄入任务。"""
    try:
        result = await service.submit_url(payload, trace_id)
        return create_success_response(result.model_dump(), trace_id)
    except ValueError as exc:
        logger.warning(f"RAG 知识 URL 入库拦截 trace_id={trace_id} reason={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)
    except Exception as exc:
        logger.error(f"提交 RAG URL 摄入失败 trace_id={trace_id} url={payload.url} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)

@router.put("/knowledge/{document_id}", response_model=ResponseModel)
async def update_knowledge_document(
    document_id: str,
    file: Annotated[UploadFile, File(...)],
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[RagIngestionService, Depends(get_ingestion_service)],
    repo: Annotated[RagPGRepository, Depends(get_rag_pg_repo)],
    strategy: Annotated[RagChunkStrategy, Form()] = RagChunkStrategy.STRUCTURED_AST,
    chunk_size: Annotated[int, Form(ge=80, le=2000)] = 500,
    overlap: Annotated[int, Form(ge=0, le=500)] = 50,
    regex_pattern: Annotated[str | None, Form(max_length=500)] = None,
) -> ResponseModel:
    """平滑更新本地知识库文档 (Blue-Green Update)，支持增量切片与向量复用。"""
    if not file.filename:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "文件名不能为空", trace_id)
        
    doc = await repo.get_document(document_id)
    if not doc:
         return create_error_response(ErrorCode.BUSINESS_ERROR, "指定的知识库文档不存在", trace_id)
         
    content = await file.read()
    if not content:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "上传文件内容不能为空", trace_id)
        
    import hashlib
    file_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)

    new_doc_id = generate_string_id()
    task_id = generate_string_id()
    
    # 建立具有 previous_version_id 的新记录
    await repo.create_document(
        document_id=new_doc_id,
        filename=file.filename,
        source_type=RagSourceType.LOCAL_FILE,
        status=RagDocumentStatus.PARSING,
        file_hash=file_hash,
        file_size=file_size,
        previous_version_id=document_id,
    )
    
    options = IngestionOptions(strategy=strategy, chunk_size=chunk_size, overlap=overlap, regex_pattern=regex_pattern)
    task = asyncio.create_task(
        service._run_file_ingestion(task_id, new_doc_id, file.filename, content, options, trace_id)
    )
    service._track_task(task)
    
    return create_success_response({"task_id": task_id, "new_document_id": new_doc_id, "original_document_id": document_id}, trace_id)


async def _generate_preview_response(
    strategy: RagChunkStrategy,
    chunk_size: int,
    overlap: int,
    max_fallback_tokens: int | None,
    regex_pattern: str | None,
    text: str,
    timeout_seconds: float,
    trace_id: str,
) -> ResponseModel:
    """内部辅助函数，统一执行切片预览并组装响应。"""
    try:
        config = ChunkerConfig(
            chunk_size=chunk_size,
            overlap=overlap,
            max_fallback_tokens=max_fallback_tokens,
            regex_pattern=regex_pattern,
        )
        chunker = build_chunker(strategy, config)
        # 对待预览文本做长度硬截断，防止解析出超长文本导致的切片计算瘫痪
        truncated_text = text[:10000]
        chunks = await asyncio.wait_for(
            asyncio.to_thread(chunker.chunk, generate_string_id(), truncated_text, {"preview": True}),
            timeout=timeout_seconds,
        )
        warnings = [chunk.metadata.get("warning", "") for chunk in chunks if chunk.metadata.get("warning")]
        response = ChunkPreviewResponse(chunks=chunks[:5], total_chunks=len(chunks), warnings=list(dict.fromkeys(warnings)))
        return create_success_response(response.model_dump(), trace_id)
    except asyncio.TimeoutError:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "切片预览超时，策略可能存在计算风险", trace_id)
    except Exception as exc:
        logger.warning(f"RAG 切片预览计算失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)


@router.post("/chunk/preview", response_model=ResponseModel)
async def preview_chunks(payload: ChunkPreviewRequest, trace_id: Annotated[str, Depends(get_trace_id)]) -> ResponseModel:
    """同步预览切片策略 (纯文本)，最多返回前 5 个切片。"""
    return await _generate_preview_response(
        strategy=payload.strategy,
        chunk_size=payload.chunk_size,
        overlap=payload.overlap,
        max_fallback_tokens=payload.max_fallback_tokens,
        regex_pattern=payload.regex_pattern,
        text=payload.text,
        timeout_seconds=payload.timeout_seconds,
        trace_id=trace_id,
    )


@router.post("/chunk/preview/file", response_model=ResponseModel)
async def preview_chunks_file(
    file: Annotated[UploadFile, File(...)],
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[RagIngestionService, Depends(get_ingestion_service)],
    strategy: Annotated[RagChunkStrategy, Form()] = RagChunkStrategy.STRUCTURED_AST,
    chunk_size: Annotated[int, Form(ge=80, le=2000)] = 500,
    overlap: Annotated[int, Form(ge=0, le=500)] = 50,
    regex_pattern: Annotated[str | None, Form(max_length=500)] = None,
) -> ResponseModel:
    """同步预览切片策略 (本地文件)，提取文本后进行切片。"""
    if not file.filename:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "文件名不能为空", trace_id)
    content = await file.read()
    if not content:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "文件内容不能为空", trace_id)
    try:
        # 复用 IngestionService 中的 document_loader 提取文本
        clean_content = await service.document_loader.extract_from_bytes(file.filename, content)
        return await _generate_preview_response(
            strategy=strategy,
            chunk_size=chunk_size,
            overlap=overlap,
            max_fallback_tokens=1000,
            regex_pattern=regex_pattern,
            text=clean_content.text,
            timeout_seconds=8.0,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(f"RAG 文件预览提取文本失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, f"解析文件失败: {exc}", trace_id)


@router.post("/chunk/preview/url", response_model=ResponseModel)
async def preview_chunks_url(
    payload: RagUrlIngestionRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[RagIngestionService, Depends(get_ingestion_service)],
) -> ResponseModel:
    """同步预览切片策略 (URL)，抓取网页正文后进行切片。"""
    try:
        # 复用 IngestionService 中的 url_loader 提取文本
        clean_content = await service.url_loader.extract(payload.url)
        return await _generate_preview_response(
            strategy=payload.strategy,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
            max_fallback_tokens=payload.max_fallback_tokens,
            regex_pattern=payload.regex_pattern,
            text=clean_content.text,
            timeout_seconds=8.0,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(f"RAG 网址预览抓取失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, f"网页抓取失败: {exc}", trace_id)


@router.post("/search", response_model=ResponseModel)
async def search_knowledge(
    payload: RagSearchRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    orchestrator: Annotated[RagRetrievalOrchestrator, Depends(get_retrieval_orchestrator)],
) -> ResponseModel:
    """执行知识库检索并返回证据与引用。"""
    try:
        result = await orchestrator.search(payload, trace_id)
        return create_success_response(result.model_dump(), trace_id)
    except Exception as exc:
        logger.error(f"RAG 知识检索失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)


@router.get("/knowledge/{document_id}", response_model=ResponseModel)
async def get_knowledge_document(
    document_id: str,
    trace_id: Annotated[str, Depends(get_trace_id)],
    repo: Annotated[RagPGRepository, Depends(get_rag_pg_repo)],
) -> ResponseModel:
    """查询单个知识库文档状态。"""
    document = await repo.get_document(document_id)
    if document is None:
        return create_error_response(ErrorCode.BUSINESS_ERROR, "知识库文档不存在", trace_id)
    return create_success_response(RagDocumentDTO.model_validate(document).model_dump(), trace_id)


@router.delete("/knowledge/{document_id}", response_model=ResponseModel)
async def delete_knowledge_document(
    document_id: str,
    trace_id: Annotated[str, Depends(get_trace_id)],
    repo: Annotated[RagPGRepository, Depends(get_rag_pg_repo)],
) -> ResponseModel:
    """删除知识库文档，清理关联的所有切片信息及向量库中的记录。"""
    try:
        document = await repo.get_document(document_id)
        if document is None:
            return create_error_response(ErrorCode.BUSINESS_ERROR, "知识库文档不存在", trace_id)
        
        # 获取 qdrant 仓库并清理对应 chunk
        from fastapi import Request
        from app.main import app as main_app
        qdrant_repo = getattr(main_app.state, "rag_qdrant_repo", None)
        
        # 在 PostgreSQL 中删除文档及关联切片，返回需要从向量库清理的 chunk_ids
        chunk_ids_to_delete = await repo.delete_document(document_id)
        
        # 在 Qdrant 中清理切片
        if qdrant_repo and chunk_ids_to_delete:
            await qdrant_repo.delete_chunks(chunk_ids_to_delete)
            
        logger.info(f"RAG 文档删除成功 document_id={document_id} chunks_deleted={len(chunk_ids_to_delete)}")
        return create_success_response({"deleted_document_id": document_id, "deleted_chunks": len(chunk_ids_to_delete)}, trace_id)
    except Exception as exc:
        logger.error(f"RAG 知识删除失败 trace_id={trace_id} document_id={document_id} error={exc}")
        return create_error_response(ErrorCode.BUSINESS_ERROR, str(exc), trace_id)


@router.get("/knowledge", response_model=ResponseModel)
async def list_knowledge_documents(
    trace_id: Annotated[str, Depends(get_trace_id)],
    repo: Annotated[RagPGRepository, Depends(get_rag_pg_repo)],
    limit: int = 100,
) -> ResponseModel:
    """列出最近知识库文档。"""
    documents = await repo.list_documents(limit=max(1, min(limit, 200)))
    return create_success_response([RagDocumentDTO.model_validate(item).model_dump() for item in documents], trace_id)
