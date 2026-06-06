"""
Luna AI 知识库混合检索器模块

做什么：编排 PostgreSQL FTS（BM25 风格）稀疏检索 + Qdrant 向量稠密检索的双路召回流水线，
         专门针对知识库 Chunk 表，合并去重后经 CrossEncoder Rerank 重排并严格截取结果。
为什么这样做：知识库 RAG 与长期记忆的底层表结构、返回类型（RagChunkCandidate vs LongTermMemory）完全不同。
             通过本模块将知识库特有的检索底层逻辑独立封装，解决原本错误复用长期记忆 HybridRetriever 的问题。
"""

import asyncio
from typing import Any, Dict, List, Optional, Protocol

from app.logger import logger
from app.repository.rag_pg import RagChunkCandidate, RagPGRepository
from app.repository.rag_qdrant import RagQdrantRepository


class InferenceService(Protocol):
    """推理服务接口（用于 Embedding 和 Rerank）"""
    async def get_embedding_vector(self, text: str) -> List[float]:
        ...

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        ...


class KnowledgeRetriever:
    """
    知识库混合检索编排器
    
    做什么：协调 PG FTS 稀疏检索 + Qdrant 向量稠密检索的全流程。
    """

    def __init__(
        self,
        pg_repo: RagPGRepository,
        qdrant_repo: Optional[RagQdrantRepository],
        inference_svc: Optional[InferenceService],
        retrieval_top_k: int = 20,
        rerank_top_k: int = 3,
    ):
        self.pg_repo = pg_repo
        self.qdrant_repo = qdrant_repo
        self.inference_svc = inference_svc
        self.retrieval_top_k = retrieval_top_k if retrieval_top_k > 0 else 5
        self.rerank_top_k = rerank_top_k if rerank_top_k > 0 else 3

    async def _vector_retrieve(self, query_text: str) -> List[tuple[RagChunkCandidate, float]]:
        """向量稠密检索（Qdrant）"""
        if not self.qdrant_repo or not self.inference_svc or not self.pg_repo:
            return []
            
        try:
            query_vector = await self.inference_svc.get_embedding_vector(query_text)
            if not query_vector:
                return []
                
            search_top_k = min(self.retrieval_top_k * 3, 50)
            vector_hits = await self.qdrant_repo.search(query_vector, search_top_k)
            if not vector_hits:
                return []
                
            candidates = await self.pg_repo.get_chunks_by_ids([hit.chunk_id for hit in vector_hits])
            hit_scores = {hit.chunk_id: hit.score for hit in vector_hits}
            
            return [(candidate, hit_scores.get(candidate.chunk.chunk_id, 0.0)) for candidate in candidates]
        except Exception as e:
            logger.warning(f"知识库 Qdrant 向量检索失败 error={e}")
            return []

    async def _fts_retrieve(self, query_text: str) -> List[tuple[RagChunkCandidate, float]]:
        """PG FTS 稀疏检索（PostgreSQL tsvector）"""
        if not query_text or not self.pg_repo:
            return []
            
        try:
            candidates = await self.pg_repo.search_by_text(query_text, self.retrieval_top_k)
            return [(candidate, candidate.score) for candidate in candidates]
        except Exception as e:
            logger.warning(f"知识库 PG FTS 检索失败 error={e}")
            return []

    async def _rerank_and_truncate(
        self,
        query_text: str,
        candidates: List[tuple[RagChunkCandidate, float]],
    ) -> List[tuple[RagChunkCandidate, float]]:
        """对合并后的列表执行 Rerank 重排并严格截断"""
        if not candidates:
            return []

        sorted_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
        
        if len(sorted_candidates) <= 1 or not query_text or not self.inference_svc:
            return sorted_candidates[:self.rerank_top_k]

        documents = [item[0].chunk.content_text for item in sorted_candidates]

        try:
            rerank_results = await self.inference_svc.rerank_documents(query_text, documents)

            reranked: List[tuple[RagChunkCandidate, float]] = []
            for result in rerank_results[:self.rerank_top_k]:
                idx = int(result.get("index", 0))
                if 0 <= idx < len(sorted_candidates):
                    candidate = sorted_candidates[idx][0]
                    new_score = float(result.get("score", sorted_candidates[idx][1]))
                    reranked.append((candidate, new_score))

            logger.info(f"知识库 Rerank 重排完成 hits={len(reranked)} rerank_top_k={self.rerank_top_k}")
            return reranked
        except Exception as e:
            logger.warning(f"知识库 Rerank 重排失败，使用原始顺序截断 error={e}")
            return sorted_candidates[:self.rerank_top_k]

    async def retrieve(
        self,
        query_text: str,
        search_mode: str = "hybrid",
    ) -> List[tuple[RagChunkCandidate, float]]:
        """
        执行完整的知识库混合检索流程

        :param query_text: 用户查询文本
        :param search_mode: 检索模式，支持 'keyword', 'vector', 'hybrid'
        :return: 经过重排截断后的切片候选列表及得分
        """
        if not self.pg_repo:
            logger.warning("PostgreSQL 知识库仓库不可用，跳过检索")
            return []

        if search_mode in ("hybrid", "vector"):
            vector_task = asyncio.create_task(self._vector_retrieve(query_text))
        else:
            vector_task = asyncio.create_task(asyncio.sleep(0, result=[]))
            
        if search_mode in ("hybrid", "keyword"):
            fts_task = asyncio.create_task(self._fts_retrieve(query_text))
        else:
            fts_task = asyncio.create_task(asyncio.sleep(0, result=[]))

        vector_results, fts_results = await asyncio.gather(vector_task, fts_task)

        # 合并去重
        merged_map: Dict[str, tuple[RagChunkCandidate, float]] = {}

        for candidate, score in fts_results:
            chunk_id = candidate.chunk.chunk_id
            merged_map[chunk_id] = (candidate, score)

        for candidate, vector_score in vector_results:
            chunk_id = candidate.chunk.chunk_id
            if chunk_id not in merged_map:
                merged_map[chunk_id] = (candidate, vector_score)
            else:
                existing_candidate, existing_score = merged_map[chunk_id]
                merged_map[chunk_id] = (existing_candidate, max(existing_score, vector_score))

        all_candidates = list(merged_map.values())

        if not all_candidates:
            logger.info(f"知识库检索无匹配结果 mode={search_mode} top_k={self.retrieval_top_k}")
            return []

        # Rerank 重排 + 截断
        result = await self._rerank_and_truncate(query_text, all_candidates)

        logger.info(
            f"知识库检索完成 mode={search_mode} merge_count={len(all_candidates)} "
            f"final_count={len(result)} rerank_top_k={self.rerank_top_k}"
        )
        return result
