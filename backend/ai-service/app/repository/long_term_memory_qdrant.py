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
from app.rag.chunker import MemoryChunk
from app.utils.snowflake import generate_id


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

    async def save_chunks_with_vectors(
        self,
        memory_id: str,
        session_id: str,
        chunks: List[MemoryChunk],
        vectors: List[List[float]],
        status: str = ""
    ) -> None:
        """
        做什么：批量将拆分后的 Chunk 及其向量存入 Qdrant。
        为什么这样做：实现细粒度的 RAG 切片存储，以便后续检索时能够进行 search_groups 分组折叠去重。
        输入：memory_id（PG记录主键），session_id，MemoryChunk 列表及其对应的向量列表。
        异常行为：Qdrant 写入异常抛出。
        """
        if not status:
            status = MemoryStatus.ACTIVE.value
            
        if len(chunks) != len(vectors):
            raise ValueError(f"chunks 数量 ({len(chunks)}) 与 vectors 数量 ({len(vectors)}) 不匹配")

        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = generate_id()  # 每个 Chunk 分配独立的 Snowflake ID
            
            point = UpsertPoint(
                id=point_id,
                vector=vector,
                payload={
                    "memory_id": memory_id,
                    "session_id": session_id,
                    "chunk_type": chunk.chunk_type.value,
                    "content": chunk.content,
                    "status": status,
                }
            )
            points.append(point)
            
        await self.client.upsert(QDRANT_COLLECTION_LONG_TERM_MEMORIES, points)
        logger.info(f"[TraceID:N/A] 长期记忆切片向量已批量保存 memory_id={memory_id} chunks_count={len(chunks)}")

    async def search_groups_by_vector(self, query_vector: List[float], top_k: int) -> List[str]:
        """
        做什么：利用 Qdrant search_groups 获取去重后的 memory_id 列表。
        为什么这样做：解决同一条 PostgreSQL 记录的多个 Chunk 同时挤占 Top-K 检索名额的问题。
        边界条件：仅返回 payload 中 status=MemoryStatus.ACTIVE.value 的分组
        """
        results = await self.client.search_groups(
            collection_name=QDRANT_COLLECTION_LONG_TERM_MEMORIES,
            query_vector=query_vector,
            group_by="memory_id",
            limit=top_k,
            group_size=1
        )
        
        active_status = MemoryStatus.ACTIVE.value
        memory_ids = []
        for group in results:
            # group.id 就是 group_by 字段的值，即 memory_id
            # group.hits 包含组内的得分最高的 chunk
            if group.hits and group.hits[0].payload and group.hits[0].payload.get("status") == active_status:
                memory_ids.append(str(group.id))
                
        logger.info(f"[TraceID:N/A] 长期记忆分组向量检索完成 groups={len(results)} active_hits={len(memory_ids)} top_k={top_k}")
        return memory_ids

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

    # TODO: soft_delete_by_memory_id & delete_vector 以后需要改成 scroll 取出所有 point 然后修改 / 删除
    # 因为现在同一个 memory_id 会对应多个 Qdrant Points。但本次改动重点在 RAG Chunking 和 search_groups。
