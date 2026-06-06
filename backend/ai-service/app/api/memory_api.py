"""
Luna AI 记忆管理 HTTP API 服务模块

做什么：提供手动记忆压缩和长期记忆 CRUD 的 HTTP 接口。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
from app.repository.models import LongTermMemory, MemoryStatus
from app.utils.snowflake import generate_string_id
from app.api.http_api import get_trace_id, APIResponse

router = APIRouter(prefix="/api/memory", tags=["memory"])

# ============================================================
# 依赖注入
# ============================================================

async def get_redis_repo(request: Request) -> Optional[ChatHistoryRedisRepo]:
    return getattr(request.app.state, "redis_repo", None)

async def get_ltm_pg_repo(request: Request) -> Optional[LongTermMemoryPGRepo]:
    return getattr(request.app.state, "ltm_pg_repo", None)

async def get_ltm_qdrant_repo(request: Request) -> Optional[LongTermMemoryQdrantRepo]:
    return getattr(request.app.state, "ltm_qdrant_repo", None)

async def get_memory_manager(request: Request) -> Optional[MemoryManager]:
    return getattr(request.app.state, "memory_manager", None)

# ============================================================
# 模型定义
# ============================================================

class CompressRequest(BaseModel):
    session_id: str

class CreateMemoryRequest(BaseModel):
    session_id: str
    summary: str

class UpdateMemoryRequest(BaseModel):
    summary: str

# ============================================================
# 手动记忆接口
# ============================================================

@router.get("/uncompressed", response_model=APIResponse)
async def get_uncompressed_sessions(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    redis_repo: Optional[ChatHistoryRedisRepo] = Depends(get_redis_repo),
) -> APIResponse:
    """获取积压的未压缩会话列表（排除当天）"""
    if not redis_repo:
        raise HTTPException(status_code=500, detail="Redis 仓库不可用")

    try:
        # 1. 从 Redis 获取所有会话 ID
        redis_session_ids = await redis_repo.get_all_session_ids()
        
        # 2. 从 PG 获取所有已经有长期记忆的 session_id
        ltm_pg_repo = getattr(request.app.state, "ltm_pg_repo", None)
        compressed_sessions = []
        if ltm_pg_repo:
            compressed_sessions = await ltm_pg_repo.get_all_active_session_ids()
            
        # 3. 过滤：排除当天、排除已入库、确保 Redis 中有实际历史记录
        today = datetime.now().strftime("%Y%m%d")
        uncompressed_ids = []
        
        client = redis_repo.redis_client.get_client()
        
        for sid in redis_session_ids:
            if sid == today:
                continue
            if sid in compressed_sessions:
                continue
                
            # 检查该会话是否有实际的历史记录
            history_key = redis_repo._build_history_key(sid)
            history_len = await client.llen(history_key)
            if history_len > 0:
                uncompressed_ids.append(sid)
                
        # 排序，保证返回顺序稳定
        uncompressed_ids.sort()
                
        return APIResponse(
            type="RES_UNCOMPRESSED_SESSIONS",
            trace_id=trace_id,
            payload={
                "count": len(uncompressed_ids),
                "session_ids": uncompressed_ids
            }
        )
    except Exception as e:
        logger.error(f"获取未压缩会话列表失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/compress", response_model=APIResponse)
async def compress_session(
    req: CompressRequest,
    trace_id: str = Depends(get_trace_id),
    memory_manager: Optional[MemoryManager] = Depends(get_memory_manager),
    redis_repo: Optional[ChatHistoryRedisRepo] = Depends(get_redis_repo),
) -> APIResponse:
    """执行单日会话压缩入库"""
    if not memory_manager or not redis_repo:
        raise HTTPException(status_code=500, detail="依赖服务不可用")

    try:
        await memory_manager._compress_and_commit(req.session_id)
        await redis_repo.delete_session(req.session_id)
        
        return APIResponse(
            type="RES_COMPRESS_SESSION",
            trace_id=trace_id,
            payload={"status": "success", "session_id": req.session_id}
        )
    except Exception as e:
        logger.error(f"压缩会话失败 trace_id={trace_id} session_id={req.session_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 长期记忆 CRUD 接口
# ============================================================

@router.get("/long_term", response_model=APIResponse)
async def get_long_term_memories(
    page: int = 1,
    page_size: int = 20,
    trace_id: str = Depends(get_trace_id),
    ltm_pg_repo: Optional[LongTermMemoryPGRepo] = Depends(get_ltm_pg_repo),
) -> APIResponse:
    """分页查询长期记忆"""
    if not ltm_pg_repo:
        raise HTTPException(status_code=500, detail="PG 仓库不可用")

    try:
        records, total = await ltm_pg_repo.get_paginated(page, page_size)
        
        items = []
        for r in records:
            items.append({
                "id": r.id,
                "session_id": r.session_id,
                "summary": r.summary,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })
            
        return APIResponse(
            type="RES_LONG_TERM_MEMORIES",
            trace_id=trace_id,
            payload={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size
            }
        )
    except Exception as e:
        logger.error(f"获取长期记忆列表失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/long_term", response_model=APIResponse)
async def create_long_term_memory(
    req: CreateMemoryRequest,
    request: Request,
    trace_id: str = Depends(get_trace_id),
    ltm_pg_repo: Optional[LongTermMemoryPGRepo] = Depends(get_ltm_pg_repo),
    ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo] = Depends(get_ltm_qdrant_repo),
) -> APIResponse:
    """新增长期记忆"""
    if not ltm_pg_repo or not ltm_qdrant_repo:
        raise HTTPException(status_code=500, detail="仓库不可用")

    memory_id = generate_string_id()
    
    try:
        # 1. 保存到 PG
        memory = LongTermMemory(
            id=memory_id,
            session_id=req.session_id,
            summary=req.summary,
            status=MemoryStatus.ACTIVE.value,
        )
        await ltm_pg_repo.save(memory)
        
        # 2. 获取 Embedding 并保存到 Qdrant
        inference_svc = getattr(request.app.state, "inference_service", None)
        embedding_vec = [0.0] * 768
        if inference_svc:
            try:
                embedding_vec = await inference_svc.get_embedding_vector(req.summary)
            except Exception as e:
                logger.warning(f"获取 Embedding 失败，使用零向量 trace_id={trace_id} error={e}")
                
        await ltm_qdrant_repo.save_with_vector(
            memory_id, req.session_id, embedding_vec, MemoryStatus.ACTIVE.value
        )
        
        return APIResponse(
            type="RES_CREATE_MEMORY",
            trace_id=trace_id,
            payload={"id": memory_id, "status": "success"}
        )
    except Exception as e:
        logger.error(f"创建长期记忆失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/long_term/{id}", response_model=APIResponse)
async def update_long_term_memory(
    id: str,
    req: UpdateMemoryRequest,
    request: Request,
    trace_id: str = Depends(get_trace_id),
    ltm_pg_repo: Optional[LongTermMemoryPGRepo] = Depends(get_ltm_pg_repo),
    ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo] = Depends(get_ltm_qdrant_repo),
) -> APIResponse:
    """修改长期记忆"""
    if not ltm_pg_repo or not ltm_qdrant_repo:
        raise HTTPException(status_code=500, detail="仓库不可用")

    try:
        # 1. 更新 PG
        await ltm_pg_repo.update_summary(id, req.summary)
        
        # 2. 获取原记录以获取 session_id
        records = await ltm_pg_repo.get_by_ids([id])
        if not records:
            raise HTTPException(status_code=404, detail="记忆不存在")
        session_id = records[0].session_id
        
        # 3. 更新 Qdrant
        inference_svc = getattr(request.app.state, "inference_service", None)
        embedding_vec = [0.0] * 768
        if inference_svc:
            try:
                embedding_vec = await inference_svc.get_embedding_vector(req.summary)
            except Exception as e:
                logger.warning(f"获取 Embedding 失败，使用零向量 trace_id={trace_id} error={e}")
                
        await ltm_qdrant_repo.save_with_vector(
            id, session_id, embedding_vec, MemoryStatus.ACTIVE.value
        )
        
        return APIResponse(
            type="RES_UPDATE_MEMORY",
            trace_id=trace_id,
            payload={"id": id, "status": "success"}
        )
    except Exception as e:
        logger.error(f"更新长期记忆失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/long_term/{id}", response_model=APIResponse)
async def delete_long_term_memory(
    id: str,
    trace_id: str = Depends(get_trace_id),
    ltm_pg_repo: Optional[LongTermMemoryPGRepo] = Depends(get_ltm_pg_repo),
    ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo] = Depends(get_ltm_qdrant_repo),
) -> APIResponse:
    """删除长期记忆"""
    if not ltm_pg_repo or not ltm_qdrant_repo:
        raise HTTPException(status_code=500, detail="仓库不可用")

    try:
        # 1. PG 硬删除
        await ltm_pg_repo.delete_hard(id)
        
        # 2. Qdrant 硬删除
        await ltm_qdrant_repo.delete_vector(id)
        
        return APIResponse(
            type="RES_DELETE_MEMORY",
            trace_id=trace_id,
            payload={"id": id, "status": "success"}
        )
    except Exception as e:
        logger.error(f"删除长期记忆失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=str(e))
