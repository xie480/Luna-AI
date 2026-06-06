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

    async def save_with_vector(
        self,
        memory_id: str,
        session_id: str,
        vector: List[float],
        status: str = ""
    ) -> None:
        """
        保存整条长期记忆向量。

        做什么：为未拆分的长期记忆摘要写入单个 Qdrant Point。
        为什么这样做：保留生产可用的整摘要向量写入能力，供单块记忆或旧任务补偿路径使用。
        输入输出：输入 memory_id、session_id、向量和状态；输出为空。
        边界条件：memory_id 必须可转换为 Snowflake 整数，向量不能为空。
        异常行为：参数非法或 Qdrant 写入失败时向上抛出。
        """
        if not status:
            status = MemoryStatus.ACTIVE.value
        if not memory_id or not vector:
            raise ValueError("memory_id 和 vector 不能为空")
        point = UpsertPoint(
            id=int(memory_id),
            vector=vector,
            payload={"memory_id": memory_id, "session_id": session_id, "status": status},
        )
        await self.client.upsert(QDRANT_COLLECTION_LONG_TERM_MEMORIES, [point])
        logger.info(f"长期记忆整摘要向量已保存 memory_id={memory_id} status={status}")

    async def soft_delete_by_memory_id(self, memory_id: str) -> None:
        """
        软删除长期记忆向量。

        做什么：写入同 ID 零向量并将 payload.status 标记为 DELETED。
        为什么这样做：Qdrant upsert 是幂等覆盖操作，可在不依赖 scroll 的情况下立即阻断旧向量召回。
        输入输出：输入 memory_id，输出为空。
        边界条件：memory_id 必须可转换为 Snowflake 整数。
        异常行为：Qdrant 写入失败时向上抛出。
        """
        await self.save_with_vector(memory_id, "", [0.0] * 768, MemoryStatus.DELETED.value)

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

    async def delete_vectors_by_memory_id(self, memory_id: str) -> None:
        """
        按长期记忆 ID 删除所有关联向量。

        做什么：通过 Qdrant scroll 找到 payload.memory_id 对应的全部切片点并删除。
        为什么这样做：同一条长期记忆会对应多个 Chunk Point，撤销记忆时必须清理全部向量，避免脏召回。
        输入输出：输入 memory_id，输出为空。
        边界条件：memory_id 为空直接抛错；未找到点时记录日志并返回。
        异常行为：Qdrant 查询或删除失败时向上抛出，由调用方决定重试或补偿。
        """
        if not memory_id:
            raise ValueError("memory_id 不能为空")
        await self.client._ensure_client()
        from qdrant_client.http import models  # type: ignore

        points: list[int] = []
        next_offset = None
        while True:
            records, next_offset = await self.client.client.scroll(
                collection_name=QDRANT_COLLECTION_LONG_TERM_MEMORIES,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="memory_id",
                            match=models.MatchValue(value=memory_id),
                        )
                    ]
                ),
                limit=128,
                offset=next_offset,
                with_payload=False,
                with_vectors=False,
            )
            points.extend(int(record.id) for record in records)
            if next_offset is None:
                break
        if not points:
            logger.info(f"长期记忆向量删除跳过，未找到关联点 memory_id={memory_id}")
            return
        await self.client.delete_points(QDRANT_COLLECTION_LONG_TERM_MEMORIES, points)
        logger.info(f"长期记忆关联向量已删除 memory_id={memory_id} points_count={len(points)}")
