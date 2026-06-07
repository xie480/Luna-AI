"""
Luna RAG Qdrant 知识库向量仓库

做什么：封装 Phase 7 知识库集合 luna_rag_index 的创建、写入、检索与删除。
为什么这样做：Qdrant 仅负责数学近邻计算，Payload 只保存 chunk_id/doc_id 映射，完整正文回表到 PostgreSQL。
输入输出：输入 ChunkUnit 与向量，输出命中的 chunk_id/doc_id/score。
边界条件：向量不能为空；Point ID 使用 chunk_id 的 Snowflake 整数字符串转换。
异常行为：Qdrant 不可用时向上抛出异常，由摄入或检索服务决定降级策略。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.qdrant import QdrantClientWrapper, UpsertPoint
from app.logger import logger
from app.rag.types import ChunkUnit
from app.types.constants import RAG_QDRANT_COLLECTION


@dataclass(frozen=True)
class RagVectorHit:
    """知识库向量命中结果。"""

    chunk_id: str
    document_id: str
    score: float


class RagQdrantRepository:
    """
    RAG 知识库 Qdrant 仓库。

    做什么：管理知识库向量集合的生命周期。
    为什么这样做：避免业务层直接操作 Qdrant Payload 和集合名称。
    """

    def __init__(self, qdrant_client: QdrantClientWrapper):
        self.client = qdrant_client

    async def ensure_collection(self, vector_size: int) -> None:
        """确保 luna_rag_index 集合存在。"""
        await self.client.ensure_collection(RAG_QDRANT_COLLECTION, vector_size)

    async def upsert_chunks(self, chunks: list[ChunkUnit], vectors: list[list[float]]) -> None:
        """
        批量写入知识切片向量。

        边界条件：chunks 与 vectors 数量必须一致，向量不能为空。
        """
        if len(chunks) != len(vectors):
            raise ValueError("知识切片数量与向量数量不一致")
        points: list[UpsertPoint] = []
        for chunk, vector in zip(chunks, vectors):
            if not vector:
                raise ValueError(f"知识切片向量不能为空 chunk_id={chunk.chunk_id}")
            points.append(
                UpsertPoint(
                    id=int(chunk.chunk_id),
                    vector=vector,
                    payload={"chunk_id": chunk.chunk_id, "doc_id": chunk.document_id},
                )
            )
        await self.client.upsert(RAG_QDRANT_COLLECTION, points)
        logger.info(f"RAG 知识切片向量写入完成 chunks_count={len(points)}")

    async def bulk_upsert(self, points: list[UpsertPoint]) -> None:
        """批量更新向量点（用于直接写入从旧文档取回的向量和新向量）"""
        if not points:
            return
        await self.client.upsert(RAG_QDRANT_COLLECTION, points)
        logger.info(f"RAG Qdrant 批量向量写入完成 count={len(points)}")

    async def batch_retrieve_vectors(self, chunk_ids: list[str]) -> dict[str, list[float]]:
        """从 Qdrant 批量拉取现有的向量，用于增量更新复用。"""
        if not chunk_ids:
            return {}
        
        # 将 chunk_id 转为 Qdrant 需要的 int ID
        qdrant_ids = [int(cid) for cid in chunk_ids if cid.isdigit()]
        if not qdrant_ids:
            return {}
            
        results = await self.client.retrieve(RAG_QDRANT_COLLECTION, qdrant_ids)
        vectors_map: dict[str, list[float]] = {}
        for result in results:
            if hasattr(result, 'vector') and result.vector:
                vectors_map[str(result.id)] = result.vector
        
        logger.info(f"RAG Qdrant 批量检索向量命中 hit_count={len(vectors_map)} req_count={len(chunk_ids)}")
        return vectors_map

    async def search(self, query_vector: list[float], top_k: int) -> list[RagVectorHit]:
        """执行知识库向量检索并返回轻量映射结果。"""
        if not query_vector:
            raise ValueError("查询向量不能为空")
        raw_results = await self.client.search(RAG_QDRANT_COLLECTION, query_vector, top_k)
        hits: list[RagVectorHit] = []
        for item in raw_results:
            chunk_id = str(item.payload.get("chunk_id", ""))
            doc_id = str(item.payload.get("doc_id", ""))
            if chunk_id and doc_id:
                hits.append(RagVectorHit(chunk_id=chunk_id, document_id=doc_id, score=float(item.score)))
        logger.info(f"RAG Qdrant 向量检索完成 hits={len(hits)} top_k={top_k}")
        return hits

    async def delete_chunks(self, chunk_ids: list[str]) -> None:
        """按 chunk_id 删除知识库向量点，用于文档删除或摄入失败回滚。"""
        if not chunk_ids:
            return
        await self.client.delete_points(RAG_QDRANT_COLLECTION, [int(chunk_id) for chunk_id in chunk_ids])
        logger.info(f"RAG Qdrant 向量删除完成 chunks_count={len(chunk_ids)}")
