"""
Luna AI 知识库混合检索器模块

做什么：编排 PostgreSQL FTS（BM25 风格）稀疏检索 + Qdrant 向量稠密检索的双路召回流水线，
         专门针对知识库 Chunk 表，合并去重后经 CrossEncoder Rerank 重排并严格截取结果。
         检索参数细化规则（与长期记忆 HybridRetriever 完全对齐）：
           - 向量检索（Vector Search）：仅使用 search_queries 和 query_text 作为后备
           - BM25 检索（Keyword Search）：使用 reference_time、temporal_deviation、
             entity_mentions 以及 query_text 综合构建查询
           - query_text（即 disambiguated_text）必须作为基础查询贯穿所有检索策略
为什么这样做：知识库 RAG 与长期记忆的底层表结构、返回类型（RagChunkCandidate vs LongTermMemory）完全不同。
             通过本模块将知识库特有的检索底层逻辑独立封装，解决原本错误复用长期记忆 HybridRetriever 的问题。
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from app.logger import logger
from app.repository.models import RagChunk, RagDocument
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
            检索参数分配规则：
              - 向量检索：仅使用 search_queries（优先），降级到 [query_text]
              - BM25 检索：使用 entity_mentions + query_text 拼接，
                并通过 reference_time/temporal_deviation 对 chunks 做时间过滤
              - query_text 作为基础查询贯穿所有检索策略
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

    async def _vector_retrieve(
        self,
        query_text: str,
        search_queries: Optional[List[str]] = None,
    ) -> List[tuple[RagChunkCandidate, float]]:
        """
        向量稠密检索（Qdrant）
        
        参数分配规则（严格对齐要求）：
          - 仅使用 search_queries 进行多 Query 并发向量检索
          - 降级后备使用 query_text（即 disambiguated_text）进行单次检索
        """
        if not self.qdrant_repo or not self.inference_svc or not self.pg_repo:
            return []

        # 确定待检索的文本列表：优先使用 search_queries，降级到 [query_text]
        query_texts: List[str] = []
        if search_queries:
            query_texts = [q for q in search_queries if q]
        if not query_texts and query_text:
            query_texts = [query_text]
        if not query_texts:
            return []

        async def _search_single_query(q: str) -> List[tuple[RagChunkCandidate, float]]:
            """对单个 query 执行 Embedding + Qdrant 检索，返回切片候选及得分"""
            try:
                query_vector = await self.inference_svc.get_embedding_vector(q)
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
                logger.warning(f"知识库 Qdrant 向量检索失败 query=\"{q[:50]}...\" error={e}")
                return []

        # 并发执行所有 query 的向量检索
        result_lists = await asyncio.gather(*[_search_single_query(q) for q in query_texts])

        # 合并去重（按 chunk_id）
        merged: Dict[str, tuple[RagChunkCandidate, float]] = {}
        for results in result_lists:
            for candidate, score in results:
                chunk_id = candidate.chunk.chunk_id
                if chunk_id not in merged:
                    merged[chunk_id] = (candidate, score)
                else:
                    _, existing_score = merged[chunk_id]
                    merged[chunk_id] = (candidate, max(existing_score, score))

        logger.info(
            f"知识库向量检索完成 search_queries={len(query_texts)} 条并发 "
            f"hits={len(merged)} top_k={min(self.retrieval_top_k * 3, 50)}"
        )
        return list(merged.values())

    async def _fts_retrieve(
        self,
        query_text: str,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> List[tuple[RagChunkCandidate, float]]:
        """
        PG FTS 稀疏检索（PostgreSQL tsvector）
        
        做什么：效仿 hybrid_retriever.py 的 _fts_retrieve，分两路并行查询：
          1. 关键词路径（_kw_search）：使用 query_text + entity_mentions 拼接为 BM25 查询文本，
             同时在结果中依据 reference_time + temporal_deviation 做时间过滤
          2. 纯时间路径（_time_search）：仅使用 reference_time + temporal_deviation 查询对应
             时间范围内的 chunks（不依赖关键词），确保纯时间线索也能命中
        
        参数分配规则（严格对齐要求）：
          - 使用 query_text + entity_mentions 拼接为 BM25 查询文本
          - 使用 reference_time + temporal_deviation 对 chunks 的 created_at 做时间过滤
          - entity_mentions 仅辅助 BM25 检索，不参与向量检索
        """
        if not query_text or not self.pg_repo:
            return []

        # 关键词查询拼接：disambiguated_text + entity_mentions
        query_parts: List[str] = [query_text]
        if entity_mentions:
            query_parts.extend(entity_mentions)
        final_query = " ".join(query_parts).strip()

        # 解析参考时间
        ref_dt = None
        ref_date_start = None
        ref_date_end = None
        max_deviation = 0

        if reference_time:
            try:
                ref_dt = datetime.fromisoformat(reference_time.replace("Z", "+00:00"))
                max_deviation = max(0, temporal_deviation)
                from datetime import timedelta
                ref_date_start = (ref_dt - timedelta(days=max_deviation)).strftime("%Y-%m-%d %H:%M:%S")
                ref_date_end = (ref_dt + timedelta(days=max_deviation)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning(f"时间戳解析失败，将忽略时间过滤 reference_time={reference_time} error={e}")
                ref_dt = None

        async def _kw_search() -> List[tuple[RagChunkCandidate, float]]:
            """关键词 FTS 检索路径，并在结果中做时间过滤（如果提供了 reference_time）"""
            if not final_query:
                return []
            try:
                candidates = await self.pg_repo.search_by_text(final_query, self.retrieval_top_k)
            except Exception as e:
                logger.warning(f"知识库 PG FTS 关键词检索失败 error={e}")
                return []

            if not candidates:
                return []

            if ref_dt is not None:
                # 在结果中对 created_at 做时间过滤
                filtered: List[tuple[RagChunkCandidate, float]] = []
                for candidate in candidates:
                    chunk_created = candidate.chunk.created_at
                    if chunk_created is None:
                        # 没有时间戳的 chunk 降级但保留
                        filtered.append((candidate, candidate.score))
                        continue
                    if hasattr(chunk_created, "to_pydatetime"):
                        chunk_created = chunk_created.to_pydatetime()
                    diff_days = abs((chunk_created - ref_dt).days)
                    if diff_days <= max_deviation:
                        filtered.append((candidate, candidate.score))

                logger.info(
                    f"知识库 PG FTS 关键词检索完成（含时间过滤） "
                    f"before={len(candidates)} after={len(filtered)} "
                    f"reference_time={reference_time} temporal_deviation={max_deviation}"
                )
                return filtered
            else:
                logger.info(f"知识库 PG FTS 关键词检索完成 hits={len(candidates)} top_k={self.retrieval_top_k}")
                return [(candidate, candidate.score) for candidate in candidates]

        async def _time_search() -> List[tuple[RagChunkCandidate, float]]:
            """纯时间检索路径：使用 created_at 日期范围直接查询 chunks"""
            if ref_date_start is None or ref_date_end is None or not self.pg_repo:
                return []
            try:
                candidates = await self.pg_repo.search_by_time_range(
                    ref_date_start, ref_date_end, self.retrieval_top_k
                )
                return [(candidate, candidate.score) for candidate in candidates]
            except Exception as e:
                logger.warning(f"知识库 PG FTS 纯时间检索失败 error={e}")
                return []

        # 并行执行两路检索
        kw_results, time_results = await asyncio.gather(_kw_search(), _time_search())

        # 合并去重（按 chunk_id）
        merged: Dict[str, tuple[RagChunkCandidate, float]] = {}
        for candidate, score in kw_results:
            chunk_id = candidate.chunk.chunk_id
            merged[chunk_id] = (candidate, score)
        for candidate, score in time_results:
            chunk_id = candidate.chunk.chunk_id
            if chunk_id not in merged:
                merged[chunk_id] = (candidate, score)
            else:
                _, existing_score = merged[chunk_id]
                merged[chunk_id] = (candidate, max(existing_score, score))

        return list(merged.values())

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
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> List[tuple[RagChunkCandidate, float]]:
        """
        执行完整的知识库混合检索流程

        参数分配规则（严格对齐要求）：
          - 向量检索（_vector_retrieve）：仅使用 search_queries，降级到 [query_text]
          - BM25 检索（_fts_retrieve）：使用 entity_mentions + query_text 拼接，
            并通过 reference_time/temporal_deviation 对 chunks 做时间过滤
          - query_text（即 disambiguated_text）作为基础查询贯穿所有检索策略

        :param query_text: disambiguated_text，作为基础查询贯穿所有策略
        :param search_mode: 检索模式，支持 'keyword', 'vector', 'hybrid'
        :param search_queries: 向量检索时使用的泛化 Query 列表（由 InputReconstructor 提取）
        :param reference_time: BM25 时间参考（ISO 时间戳字符串或 None）
        :param temporal_deviation: BM25 时间过滤允许的偏差天数（0 表示精确匹配）
        :param entity_mentions: BM25 检索时的实体关键词列表
        :return: 经过重排截断后的切片候选列表及得分
        """
        if not self.pg_repo:
            logger.warning("PostgreSQL 知识库仓库不可用，跳过检索")
            return []

        # 阶段 1 & 2: 向量检索与 PG FTS 并行执行
        # 向量检索：仅使用 search_queries（或降级 query_text）
        if search_mode in ("hybrid", "vector"):
            vector_task = asyncio.create_task(
                self._vector_retrieve(query_text, search_queries)
            )
        else:
            vector_task = asyncio.create_task(asyncio.sleep(0, result=[]))
            
        # BM25 检索：使用 entity_mentions + query_text + reference_time
        if search_mode in ("hybrid", "keyword"):
            fts_task = asyncio.create_task(
                self._fts_retrieve(query_text, reference_time, temporal_deviation, entity_mentions)
            )
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
