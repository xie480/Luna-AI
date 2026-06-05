"""
Luna AI Qdrant 长期记忆存储库

做什么：封装 Qdrant 中长期记忆的向量检索操作。
为什么这样做：Qdrant 作为语义检索引擎，通过向量相似度快速定位相关的历史记忆。
输入输出：
    - LongTermMemoryQdrantRepo: 长期记忆向量存储库类
边界条件：
    - 仅返回 payload 中 status=MemoryStatus.ACTIVE.value 的记录
异常行为：
    - 数据库操作失败时抛出异常
"""

from typing import List

from app.infrastructure.qdrant import (
    QDRANT_COLLECTION_LONG_TERM_MEMORIES,
    QdrantClientWrapper,
    QdrantSearchResult,
    UpsertPoint,
)
from app.logger import logger
from app.repository.models import MemoryStatus


class LongTermMemoryQdrantRepo:
    """封装 Qdrant 中长期记忆的向量检索操作"""

    def __init__(self, qdrant_client: QdrantClientWrapper):
        self.client = qdrant_client

    async def ensure_collection(self, vector_size: int) -> None:
        """
        确保长期记忆集合存在
        向量维度：768（默认与 BGE-base-zh-v1.5 对齐）
        """
        await self.client.ensure_collection(QDRANT_COLLECTION_LONG_TERM_MEMORIES, vector_size)

    async def save_with_vector(self, memory_id: str, session_id: str, vector: List[float], status: str = "") -> None:
        """
        保存长期记忆向量
        """
        if not status:
            status = MemoryStatus.ACTIVE.value
            
        # Qdrant ID 必须是 uint64 或 UUID，这里我们将 memory_id 存储在 payload 中，
        # 并使用 snowflake ID 的 uint64 形式作为 Qdrant ID
        try:
            qdrant_id = int(memory_id)
        except ValueError:
            raise ValueError(f"memory_id 必须是可转换为整数的字符串: {memory_id}")
            
        point = UpsertPoint(
            id=qdrant_id,
            vector=vector,
            payload={
                "memory_id": memory_id,
                "session_id": session_id,
                "status": status,
            }
        )
        
        await self.client.upsert(QDRANT_COLLECTION_LONG_TERM_MEMORIES, [point])
        logger.info(f"长期记忆向量已保存 memory_id={memory_id} session_id={session_id}")

    async def search_by_vector(self, vector: List[float], top_k: int) -> List[QdrantSearchResult]:
        """
        根据向量检索长期记忆
        边界条件：仅返回 payload 中 status=MemoryStatus.ACTIVE.value 的记录
        """
        results = await self.client.search(QDRANT_COLLECTION_LONG_TERM_MEMORIES, vector, top_k)
        
        # 过滤掉 status!=MemoryStatus.ACTIVE.value 的结果
        active_status = MemoryStatus.ACTIVE.value
        active_results = [
            res for res in results 
            if res.payload.get("status") == active_status
        ]
        
        logger.info(f"长期记忆向量检索完成 hits={len(active_results)} top_k={top_k}")
        return active_results

    async def soft_delete_by_memory_id(self, memory_id: str) -> None:
        """
        根据记忆 ID 软删除向量（更新 payload 中的 status）
        """
        try:
            qdrant_id = int(memory_id)
        except ValueError:
            raise ValueError(f"memory_id 必须是可转换为整数的字符串: {memory_id}")
            
        # Qdrant 不支持直接修改 payload 中单个字段，需重新 Upsert
        # 使用空向量 + MemoryStatus.DELETED.value 状态覆盖
        # 使用零值向量覆盖：后续搜索时不会被匹配到（余弦相似度极低）
        point = UpsertPoint(
            id=qdrant_id,
            vector=[0.0] * 768, # 假设维度为 768
            payload={
                "memory_id": memory_id,
                "status": MemoryStatus.DELETED.value,
            }
        )
        
        await self.client.upsert(QDRANT_COLLECTION_LONG_TERM_MEMORIES, [point])
        logger.info(f"长期记忆向量已软删除 memory_id={memory_id}")

    async def delete_vector(self, memory_id: str) -> None:
        """
        硬删除指定的长期记忆向量
        """
        try:
            qdrant_id = int(memory_id)
        except ValueError:
            raise ValueError(f"memory_id 必须是可转换为整数的字符串: {memory_id}")
            
        await self.client.delete(QDRANT_COLLECTION_LONG_TERM_MEMORIES, [qdrant_id])
        logger.info(f"长期记忆向量已硬删除 memory_id={memory_id}")
