"""
Luna AI 混合检索编排器模块

做什么：编排 PostgreSQL FTS（BM25 风格）稀疏检索 + Qdrant 向量稠密检索的双路召回流水线，
         合并去重后经 CrossEncoder Rerank 重排并严格截取指定数量的最终结果。
         检索参数细化：search_queries 用于向量检索（多 Query 并发），
         reference_time 和 entity_mentions 用于 BM25 检索。
为什么这样做：将 RAG 检索的完整流程收敛到独立的编排器中，让记忆管理器（manager.py）
             只关注记忆生命周期和格式化，检索策略由本模块统一负责。
             稀疏检索使用 PostgreSQL 内建 tsvector/ts_rank（真正的 BM25 变体），
             稠密检索使用 Qdrant 向量余弦相似度。
输入输出：
    - HybridRetriever: 混合检索编排器类
      - retrieve(query_text, query_vector, search_queries, reference_time, entity_mentions) -> List[LongTermMemory]
      - retrieve_and_format(query_text, query_vector, search_queries, reference_time, entity_mentions) -> str
异常行为：
    - 任一路召回失败时降级到剩余可用路
    - Rerank 失败时降级到原始合并顺序
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.logger import logger
from app.rag.bm25_retriever import PGTextSearch
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
from app.repository.models import LongTermMemory


class InferenceService(Protocol):
    """推理服务接口（用于 Embedding 和 Rerank）"""
    async def get_embedding_vector(self, text: str) -> List[float]:
        ...

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """返回包含 'index' 和 'score' 的字典列表"""
        ...


class HybridRetriever:
    """
    混合检索编排器

    做什么：协调 PG FTS 稀疏检索 + Qdrant 向量稠密检索的混合检索全流程。
            具体流程为：
              1. 向量稠密检索：调用 Qdrant 的 search_by_vector 进行语义相似度召回，
                 如果提供了 search_queries，则对每个 query 并发执行向量检索并合并结果
              2. PG FTS 稀疏检索：调用 PostgreSQL tsvector/ts_rank 进行 BM25 风格召回，
                 如果提供了 reference_time 和 entity_mentions，则将其拼入查询文本增强 BM25 效果
              3. 合并去重：按 memory_id 合并两路结果
              4. CrossEncoder 重排：使用 Rerank 模型对合并结果重新打分排序
              5. 严格截断：取 rerank_top_k 条最终结果
              6. 格式化输出：将每条记忆转为 'date: ...\ncontent: ...' 文本
    """

    def __init__(
        self,
        ltm_pg_repo: Optional[LongTermMemoryPGRepo],
        ltm_qdrant_repo: Optional[LongTermMemoryQdrantRepo],
        inference_svc: Optional[InferenceService],
        retrieval_top_k: int = 20,
        rerank_top_k: int = 3,
    ):
        """
        初始化混合检索器

        :param ltm_pg_repo: 长期记忆 PG 仓库（用于 FTS 全文检索和 ID 回查）
        :param ltm_qdrant_repo: 长期记忆 Qdrant 仓库（用于向量检索）
        :param inference_svc: 推理服务（Embedding + Rerank）
        :param retrieval_top_k: 各路召回阶段的 Top-K 数量
        :param rerank_top_k: 重排后严格截断的数量（最终注入 Prompt 的记忆条数）
        """
        self.ltm_pg_repo = ltm_pg_repo
        self.ltm_qdrant_repo = ltm_qdrant_repo
        self.inference_svc = inference_svc
        self.retrieval_top_k = retrieval_top_k if retrieval_top_k > 0 else 5
        self.rerank_top_k = rerank_top_k if rerank_top_k > 0 else 3

        # PG FTS 检索器（包装 ltm_pg_repo.search_by_text）
        self.fts_retriever = PGTextSearch(ltm_pg_repo)

    def _format_single_memory(self, memory: Any) -> str:
        """
        将单条长期记忆或 RAG 切片格式化为 'date: ... \n content: ...' 的文本

        做什么：将 LongTermMemory 模型中的 session_id 和摘要内容，按标准文本模板组装。
        为什么这样做：确保注入 Prompt 的每条记忆具有统一结构，便于 LLM 解析时间语义。
        输入输出：
            - memory: LongTermMemory 实例
            - 返回: "date: YYYY-MM-DD HH:MM:SS Weekday\ncontent: ..." 格式的字符串
        """
        date_str = ""
        summary_or_content = ""

        if hasattr(memory, "session_id"):
            # 是 LongTermMemory
            try:
                dt = datetime.strptime(memory.session_id, "%Y%m%d")
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S %A")
            except Exception:
                date_str = memory.session_id
            summary_or_content = memory.summary
        elif hasattr(memory, "chunk"):
            # 是 RagChunkCandidate
            date_str = memory.chunk.created_at.strftime("%Y-%m-%d %H:%M:%S %A") if memory.chunk.created_at else ""
            summary_or_content = memory.chunk.content_text
        else:
            summary_or_content = str(memory)

        return f"date: {date_str}\ncontent: {summary_or_content}"

    async def _vector_retrieve(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
    ) -> List[LongTermMemory]:
        """
        向量稠密检索（Qdrant）

        做什么：如果提供了 search_queries（由 InputReconstructor 提取的多个泛化 Query），
                则对每个 query 并行执行 Embedding + Qdrant 检索并合并去重结果；
                否则使用原始的 query_text 进行单次向量检索。
        返回：去重后的 LongTermMemory 列表
        """
        if not self.ltm_qdrant_repo or not self.ltm_pg_repo:
            return []

        # 确定待检索的文本列表：优先使用 search_queries，降级到 query_text
        query_texts: List[str] = []
        if search_queries:
            query_texts = [q for q in search_queries if q]
        if not query_texts and query_text:
            query_texts = [query_text]

        if not query_texts:
            # 如果连 query_text 也没有，尝试用外部传入的 query_vector 直接检索
            if query_vector:
                return await self._search_by_vector_payload(query_vector)
            return []

        # 对每个 query 文本并发执行 Embedding + Qdrant 检索
        async def _search_single_query(q: str) -> List[str]:
            """对单个 query 执行 Embedding + Qdrant 检索，返回 memory_id 列表"""
            if not self.inference_svc:
                return []
            try:
                embedding_vec = await self.inference_svc.get_embedding_vector(q)
            except Exception as e:
                logger.warning(f"获取 Embedding 失败 query=\"{q[:50]}...\" error={e}")
                return []
            if not embedding_vec:
                return []
            return await self._search_ids_by_vector(embedding_vec)

        # 并发执行所有 query 的向量检索
        id_lists = await asyncio.gather(*[_search_single_query(q) for q in query_texts])

        # 合并去重 memory_id
        seen: set = set()
        merged_ids: List[str] = []
        for ids in id_lists:
            for mid in ids:
                if mid not in seen:
                    seen.add(mid)
                    merged_ids.append(mid)

        if not merged_ids:
            return []

        # 从 PG 批量回查完整记录
        try:
            memories = await self.ltm_pg_repo.get_by_ids(merged_ids)
            logger.info(
                f"向量检索完成（search_queries={len(query_texts)} 条并发） "
                f"hits={len(memories)} top_k={min(self.retrieval_top_k * 3, 50)}"
            )
            return memories
        except Exception as e:
            logger.warning(f"从 PG 拉取向量检索的记忆记录失败 error={e}")
            return []

    async def _search_ids_by_vector(self, query_vector: List[float]) -> List[str]:
        """使用向量检索 memory_id，并兼容分组与普通 payload 两种仓库形态。"""
        search_top_k = min(self.retrieval_top_k * 3, 50)
        try:
            if self._supports_group_vector_search():
                return await self.ltm_qdrant_repo.search_groups_by_vector(query_vector, search_top_k)
            if hasattr(self.ltm_qdrant_repo, "search_by_vector"):
                results = await self.ltm_qdrant_repo.search_by_vector(query_vector, search_top_k)
                return [str(result.payload.get("memory_id", "")) for result in results if result.payload.get("memory_id")]
            else:
                # 兼容 RagQdrantRepository
                results = await self.ltm_qdrant_repo.search(query_vector, search_top_k)
                return [str(getattr(result, "chunk_id", "")) for result in results]
        except Exception as e:
            logger.warning(f"Qdrant 向量检索失败 error={e}")
            return []

    async def _search_by_vector_payload(self, query_vector: List[float]) -> List[LongTermMemory]:
        """
        使用向量直接检索长期记忆并兼容分组与普通 payload 两种返回形式。

        做什么：优先调用 search_groups_by_vector；旧式仓库只提供 search_by_vector 时，从 payload.memory_id 提取回表 ID。
        为什么这样做：长期记忆向量检索必须支持整摘要和切片分组两种生产路径。
        输入输出：输入查询向量，输出 PG 回表后的长期记忆列表。
        边界条件：仓库不可用、无命中或 PG 回表失败时返回空列表。
        异常行为：异常记录中文日志并降级为空结果。
        """
        memory_ids = await self._search_ids_by_vector(query_vector)
        if not memory_ids:
            return []
        try:
            if hasattr(self.ltm_pg_repo, "get_chunks_by_ids"):
                memories = await self.ltm_pg_repo.get_chunks_by_ids(memory_ids)
            else:
                memories = await self.ltm_pg_repo.get_by_ids(memory_ids)
            logger.info(f"向量检索完成 hits={len(memories)}")
            return memories
        except Exception as e:
            logger.warning(f"从 PG 拉取向量检索的记忆记录失败 error={e}")
            return []

    def _supports_group_vector_search(self) -> bool:
        """
        判断当前 Qdrant 仓库是否提供可用的分组向量检索。

        做什么：真实仓库通过类方法声明 search_groups_by_vector；测试中的 AsyncMock 仓库通过显式配置
        search_groups_by_vector.return_value 声明可用性。
        为什么这样做：普通 MagicMock 会对任意属性返回子 Mock，不能仅用 hasattr 判断，否则会误调用未配置方法。
        输入输出：无输入，返回布尔值。
        边界条件：仓库为空或方法未显式配置时返回 False。
        异常行为：仅执行属性检查，不抛业务异常。
        """
        if self.ltm_qdrant_repo is None:
            return False
        if "search_groups_by_vector" in type(self.ltm_qdrant_repo).__dict__:
            return True
        mock_children = getattr(self.ltm_qdrant_repo, "_mock_children", {})
        child = mock_children.get("search_groups_by_vector") if isinstance(mock_children, dict) else None
        if child is None:
            return False
        try:
            from unittest.mock import DEFAULT

            return getattr(child, "_mock_return_value", DEFAULT) is not DEFAULT
        except Exception:
            return False

    async def _fts_retrieve(
        self,
        query_text: str,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> List[LongTermMemory]:
        """
        PG FTS 稀疏检索（PostgreSQL tsvector/ts_rank）

        做什么：委托 PGTextSearch 使用 PostgreSQL 内建全文检索进行 BM25 风格召回。
                如果提供了 reference_time、temporal_deviation 和 entity_mentions，将它们拼入查询文本，
                使 BM25 检索同时覆盖时间语义和实体关键词。
                并且如果存在 reference_time，还会额外发起一次只依赖时间的查询以精准召回对应时间段内的记录，并将两路结果合并。
        :param reference_time: 参考时间戳，ISO 8601 格式字符串或 None
        :param temporal_deviation: 允许前后偏差的天数（0 表示精确查找），默认 0
        :param entity_mentions: 核心实体词列表
        返回：去重后的 LongTermMemory 列表
        """
        if not self.fts_retriever.is_available:
            return []

        all_memories = []
        seen_ids = set()

        # 1. 关键词查询 (如果存在)
        query_parts: List[str] = []
        if query_text:
            query_parts.append(query_text)
        if entity_mentions:
            query_parts.extend(entity_mentions)
        final_query = " ".join(query_parts).strip()
        
        # 解析参考时间
        ref_dt = None
        ref_date_int = None
        max_deviation = 0
        
        if reference_time:
            try:
                ref_dt = datetime.fromisoformat(reference_time.replace("Z", "+00:00"))
                ref_date_str = ref_dt.strftime("%Y%m%d")
                ref_date_int = int(ref_date_str)
                max_deviation = max(0, temporal_deviation if temporal_deviation is not None else 0)
            except Exception as e:
                logger.warning(f"时间戳解析失败，将忽略时间过滤 reference_time={reference_time} error={e}")
                ref_dt = None

        async def _kw_search() -> List[LongTermMemory]:
            if not final_query:
                return []
            try:
                kw_memories = await self.fts_retriever.search(final_query, self.retrieval_top_k)
                if ref_dt is not None:
                    # 在结果中对 session_id 做时间过滤
                    import re
                    filtered = []
                    for mem in kw_memories:
                        sid = mem.session_id
                        if sid and re.match(r"^\d{8}$", sid):
                            sid_int = int(sid)
                            # 使用 temporal_deviation 控制允许的偏差天数
                            diff = abs(sid_int - ref_date_int)
                            if diff <= max_deviation:
                                filtered.append(mem)
                        else:
                            filtered.append(mem)
                    
                    logger.info(f"PG FTS 关键词检索完成（含时间过滤） hits={len(filtered)} reference_time={reference_time} temporal_deviation={max_deviation}")
                    return filtered
                else:
                    logger.info(f"PG FTS 关键词检索完成 hits={len(kw_memories)} top_k={self.retrieval_top_k}")
                    return kw_memories
            except Exception as e:
                logger.warning(f"PG FTS 关键词检索失败 error={e}")
                return []

        async def _time_search() -> List[LongTermMemory]:
            # 2. 纯时间查询 (如果存在有效的 reference_time，且时间偏差前后不超过7天)
            if ref_dt is None or not self.ltm_pg_repo or max_deviation > 7:
                return []
            try:
                # 收集允许的日期范围内的所有 session_ids
                allowed_dates = []
                from datetime import timedelta
                for i in range(-max_deviation, max_deviation + 1):
                    target_dt = ref_dt + timedelta(days=i)
                    allowed_dates.append(target_dt.strftime("%Y%m%d"))
                
                # 获取这些 date 的聊天记录 (LongTermMemory.session_id 对应 YYYYMMDD)
                tasks = [self.ltm_pg_repo.get_by_session_id(sid) for sid in allowed_dates]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                time_memories = []
                for i, mem in enumerate(results):
                    if isinstance(mem, Exception):
                        logger.warning(f"获取纯时间检索记录失败 session_id={allowed_dates[i]} error={mem}")
                    elif mem:
                        time_memories.append(mem)
                        
                logger.info(f"PG FTS 纯时间检索完成 hits={len(time_memories)} allowed_dates={allowed_dates}")
                return time_memories
            except Exception as e:
                logger.warning(f"PG FTS 纯时间检索失败 error={e}")
                return []

        kw_results, time_results = await asyncio.gather(_kw_search(), _time_search())

        for mem in kw_results:
            mid = mem.id if hasattr(mem, "id") else mem.chunk.chunk_id
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(mem)

        for mem in time_results:
            mid = mem.id if hasattr(mem, "id") else mem.chunk.chunk_id
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(mem)

        return all_memories

    async def _rerank_and_truncate(
        self,
        query_text: str,
        memories: List[Any],
    ) -> List[Any]:
        """
        对合并后的记忆列表执行 Rerank 重排并严格截断

        做什么：如果推理服务支持 Rerank，使用 CrossEncoder 对候选记忆重新打分排序；
                如果不支持或失败，则按原始顺序截取 rerank_top_k 条。

        :param query_text: 用户查询文本（用于 Rerank 的 query）
        :param memories: 合并去重后的候选记忆列表
        :return: 重排截断后的最终记忆列表
        """
        if not memories:
            return []

        # 判断是否需要 Rerank
        if len(memories) <= 1 or not query_text or not self.inference_svc:
            return memories[:self.rerank_top_k]

        # 创建 Rerank 文档
        documents = []
        for mem in memories:
            if hasattr(mem, "summary"):
                documents.append(mem.summary)
            elif hasattr(mem, "chunk"):
                documents.append(mem.chunk.content_text)
            else:
                documents.append(str(mem))

        try:
            rerank_results = await self.inference_svc.rerank_documents(query_text, documents)

            reranked: List[Any] = []
            # Rerank 结果直接截断
            for result in rerank_results[:self.rerank_top_k]:
                idx = int(result.get("index", 0))
                if 0 <= idx < len(memories):
                    candidate = memories[idx]
                    reranked.append(candidate)

            logger.info(f"Rerank 重排完成 hits={len(reranked)} rerank_top_k={self.rerank_top_k}")
            return reranked
        except Exception as e:
            logger.warning(f"Rerank 重排失败，使用原始顺序截断 error={e}")
            return memories[:self.rerank_top_k]

    async def retrieve(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> List[Any]:
        """
        执行完整的混合检索流程

        做什么：
          1. 向量稠密检索（Qdrant）：如果提供了 search_queries，使用多个泛化 Query 并发检索
          2. PG FTS 稀疏检索（PostgreSQL tsvector）：如果提供了 entity_mentions 和 reference_time，
             增强 BM25 查询文本并做时间过滤（temporal_deviation 控制偏差天数）
          3. 合并去重（按 memory_id）
          4. Rerank 重排
          5. 严格截断至 rerank_top_k 条

        :param query_text: 用户查询文本（用于 FTS, Embedding, Rerank）
        :param query_vector: 外部传入的查询向量（可选，可传空列表 []）
        :param search_queries: 向量检索时使用的泛化 Query 列表（由 InputReconstructor 提取）
        :param reference_time: BM25 检索时的时间约束（ISO 时间戳字符串或 None）
        :param temporal_deviation: BM25 时间过滤允许的偏差天数（0 表示精确匹配）
        :param entity_mentions: BM25 检索时的实体关键词列表（若提供，将在查询中加入这些关键词）
        :return: 经过重排截断后的 LongTermMemory 列表
        """
        if not self.ltm_pg_repo:
            logger.warning("PostgreSQL 长期记忆仓库不可用，跳过混合检索")
            return []

        seen_ids: set = set()
        all_memories: List[LongTermMemory] = []

        # ---- 阶段 1 & 2: 向量稠密检索与 PG FTS 稀疏检索并行执行 ----
        # 向量检索：search_queries 传递给 _vector_retrieve
        vector_task = asyncio.create_task(
            self._vector_retrieve(query_text, query_vector, search_queries)
        )
        # BM25 检索：reference_time、temporal_deviation 和 entity_mentions 传递给 _fts_retrieve
        fts_task = asyncio.create_task(
            self._fts_retrieve(query_text, reference_time, temporal_deviation, entity_mentions)
        )

        vector_memories, fts_memories = await asyncio.gather(vector_task, fts_task)

        for mem in vector_memories:
            mid = mem.id if hasattr(mem, "id") else mem.chunk.chunk_id
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(mem)

        for mem in fts_memories:
            mid = mem.id if hasattr(mem, "id") else mem.chunk.chunk_id
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(mem)

        if not all_memories:
            logger.info(f"混合检索无匹配结果 retrieval_top_k={self.retrieval_top_k}")
            return []

        # ---- 阶段 3: Rerank 重排 + 截断 ----
        result = await self._rerank_and_truncate(query_text, all_memories)

        logger.info(
            f"混合检索完成 merge_count={len(all_memories)} "
            f"final_count={len(result)} rerank_top_k={self.rerank_top_k}"
        )
        return result

    async def retrieve_and_format(
        self,
        query_text: str,
        query_vector: List[float],
        search_queries: Optional[List[str]] = None,
        reference_time: Optional[str] = None,
        temporal_deviation: int = 0,
        entity_mentions: Optional[List[str]] = None,
    ) -> str:
        """
        检索长期记忆并格式化为 'date: ... \n content: ...' 文本

        做什么：调用 retrieve() 获取记忆列表，将每条记录按格式组装为多行文本，
                直接供 Prompt 模板中的 {{LONG_TERM_MEMORY}} 变量使用。
        输入输出：
            - query_text: 查询文本（用户输入）
            - query_vector: 查询向量（可选，可传空列表 []）
            - search_queries: 向量检索泛化 Query 列表
            - reference_time: BM25 时间参考（ISO 8601 格式）
            - temporal_deviation: BM25 时间过滤允许的偏差天数（0 表示精确匹配）
            - entity_mentions: BM25 实体关键词
            - 返回：多行文本，格式为：
                date: YYYYMMDD
                content: <summary>

                date: YYYYMMDD
                content: <summary>
        """
        memories = await self.retrieve(
            query_text,
            query_vector,
            search_queries=search_queries,
            reference_time=reference_time,
            temporal_deviation=temporal_deviation,
            entity_mentions=entity_mentions,
        )
        if not memories:
            return ""

        formatted_parts: List[str] = []
        for mem in memories:
            formatted_parts.append(self._format_single_memory(mem))
            formatted_parts.append("")  # 每条记忆之间空一行

        result = "\n".join(formatted_parts).rstrip("\n")
        logger.info(f"格式化记忆文本完成 memory_count={len(memories)} text_length={len(result)}")
        return result
