"""
Luna AI 混合检索编排器模块

做什么：编排 PostgreSQL FTS（BM25 风格）稀疏检索 + Qdrant 向量稠密检索的双路召回流水线，
        合并去重后经 CrossEncoder Rerank 重排并严格截取指定数量的最终结果。
为什么这样做：将 RAG 检索的完整流程收敛到独立的编排器中，让记忆管理器（manager.py）
             只关注记忆生命周期和格式化，检索策略由本模块统一负责。
             稀疏检索使用 PostgreSQL 内建 tsvector/ts_rank（真正的 BM25 变体），
             稠密检索使用 Qdrant 向量余弦相似度。
输入输出：
    - HybridRetriever: 混合检索编排器类
      - retrieve(query_text, query_vector) -> List[LongTermMemory]
      - retrieve_and_format(query_text, query_vector) -> str
异常行为：
    - 任一路召回失败时降级到剩余可用路
    - Rerank 失败时降级到原始合并顺序
"""

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
              1. 向量稠密检索：调用 Qdrant 的 search_by_vector 进行语义相似度召回
              2. PG FTS 稀疏检索：调用 PostgreSQL tsvector/ts_rank 进行 BM25 风格召回
              3. 合并去重：按 memory_id 合并两路结果
              4. CrossEncoder 重排：使用 Rerank 模型对合并结果重新打分排序
              5. 严格截断：取 rerank_top_k 条最终结果
              6. 格式化输出：将每条记忆转为 'date: ...\\ncontent: ...' 文本
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

    def _format_single_memory(self, memory: LongTermMemory) -> str:
        """
        将单条长期记忆格式化为 'date: ... \\n content: ...' 的文本

        做什么：将 LongTermMemory 模型中的时间戳和摘要内容，按标准文本模板组装。
        为什么这样做：确保注入 Prompt 的每条记忆具有统一结构，便于 LLM 解析时间语义。
        输入输出：
            - memory: LongTermMemory 实例
            - 返回: "date: YYYY-MM-DD\\ncontent: ..." 格式的字符串
        """
        date_str = ""
        if memory.created_at:
            try:
                if hasattr(memory.created_at, 'strftime'):
                    date_str = memory.created_at.strftime("%Y-%m-%d")
                else:
                    date_str = str(memory.created_at)[:10]
            except Exception:
                date_str = ""
        return f"date: {date_str}\ncontent: {memory.summary}"

    async def _vector_retrieve(
        self,
        query_text: str,
        query_vector: List[float],
    ) -> List[LongTermMemory]:
        """
        向量稠密检索（Qdrant）

        做什么：将查询文本转为 Embedding 向量后在 Qdrant 中执行余弦相似度搜索，
                返回最多 retrieval_top_k * 3 条候选结果（为 Rerank 提供足够候选）。
        返回：去重后的 LongTermMemory 列表
        """
        if not self.ltm_qdrant_repo or not self.ltm_pg_repo:
            return []

        # 1. 获取查询向量
        final_query_vector = query_vector
        if query_text and self.inference_svc:
            try:
                embedding_vec = await self.inference_svc.get_embedding_vector(query_text)
                if embedding_vec:
                    final_query_vector = embedding_vec
            except Exception as e:
                logger.warning(f"获取查询向量的 Embedding 失败， error={e}")

        if not final_query_vector:
            return []

        # 2. 执行 Qdrant 检索（3 倍候选，上限 50）
        search_top_k = min(self.retrieval_top_k * 3, 50)

        try:
            results = await self.ltm_qdrant_repo.search_by_vector(final_query_vector, search_top_k)
        except Exception as e:
            logger.warning(f"Qdrant 向量检索失败 error={e}")
            return []

        if not results:
            return []

        # 3. 提取 memory_id 并回查 PG
        memory_ids = []
        for result in results:
            mem_id = result.payload.get("memory_id")
            memory_ids.append(str(mem_id) if mem_id else str(result.id))

        try:
            memories = await self.ltm_pg_repo.get_by_ids(memory_ids)
            logger.info(f"向量检索完成 hits={len(memories)} top_k={search_top_k}")
            return memories
        except Exception as e:
            logger.warning(f"从 PG 拉取向量检索的记忆记录失败 error={e}")
            return []

    async def _fts_retrieve(self, query_text: str) -> List[LongTermMemory]:
        """
        PG FTS 稀疏检索（PostgreSQL tsvector/ts_rank）

        做什么：委托 PGTextSearch 使用 PostgreSQL 内建全文检索进行 BM25 风格召回。
        为什么这样做：相比内存 BM25，PG FTS 无需手动维护索引失效逻辑，
                     写入即检，且 ts_rank 实现基于真正的 BM25 变体。
        返回：去重后的 LongTermMemory 列表
        """
        if not query_text or not self.fts_retriever.is_available:
            return []

        try:
            memories = await self.fts_retriever.search(query_text, self.retrieval_top_k)
            return memories
        except Exception as e:
            logger.warning(f"PG FTS 检索失败（降级跳过） error={e}")
            return []

    async def _rerank_and_truncate(
        self,
        query_text: str,
        memories: List[LongTermMemory],
    ) -> List[LongTermMemory]:
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
        documents = [mem.summary for mem in memories]

        try:
            rerank_results = await self.inference_svc.rerank_documents(query_text, documents)

            reranked: List[LongTermMemory] = []
            # 截取前 limit 条
            limit = min(self.rerank_top_k, len(rerank_results))
            for i in range(limit):
                idx = rerank_results[i].get("index", 0)
                if 0 <= idx < len(memories):
                    reranked.append(memories[idx])

            logger.info(f"Rerank 重排完成 hits={len(reranked)} rerank_top_k={self.rerank_top_k}")
            return reranked
        except Exception as e:
            logger.warning(f"Rerank 重排失败，使用原始顺序截断 error={e}")
            return memories[:self.rerank_top_k]

    async def retrieve(self, query_text: str, query_vector: List[float]) -> List[LongTermMemory]:
        """
        执行完整的混合检索流程

        做什么：
          1. 向量稠密检索（Qdrant）
          2. PG FTS 稀疏检索（PostgreSQL tsvector）
          3. 合并去重（按 memory_id）
          4. Rerank 重排
          5. 严格截断至 rerank_top_k 条
        为什么这样做：混合检索（Dense + Sparse）能兼顾语义相似度与关键词匹配，
                     显著提升长尾场景的召回率；Rerank 精排确保最终注入 Prompt 的是相关性最高的记忆。

        :param query_text: 用户查询文本（用于 FTS, Embedding, Rerank）
        :param query_vector: 外部传入的查询向量（可选，可传空列表 []）
        :return: 经过重排截断后的 LongTermMemory 列表
        """
        if not self.ltm_pg_repo:
            logger.warning("PostgreSQL 长期记忆仓库不可用，跳过混合检索")
            return []

        seen_ids: set = set()
        all_memories: List[LongTermMemory] = []

        # ---- 阶段 1: 向量稠密检索 ----
        vector_memories = await self._vector_retrieve(query_text, query_vector)
        for mem in vector_memories:
            if mem.id not in seen_ids:
                seen_ids.add(mem.id)
                all_memories.append(mem)

        # ---- 阶段 2: PG FTS 稀疏检索 ----
        fts_memories = await self._fts_retrieve(query_text)
        for mem in fts_memories:
            if mem.id not in seen_ids:
                seen_ids.add(mem.id)
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

    async def retrieve_and_format(self, query_text: str, query_vector: List[float]) -> str:
        """
        检索长期记忆并格式化为 'date: ... \\n content: ...' 文本

        做什么：调用 retrieve() 获取记忆列表，将每条记录按格式组装为多行文本，
                直接供 Prompt 模板中的 {{LONG_TERM_MEMORY}} 变量使用。
        输入输出：
            - query_text: 查询文本（用户输入）
            - query_vector: 查询向量（可选，可传空列表 []）
            - 返回：多行文本，格式为：
                date: YYYY-MM-DD
                content: <summary>

                date: YYYY-MM-DD
                content: <summary>
        """
        memories = await self.retrieve(query_text, query_vector)
        if not memories:
            return ""

        formatted_parts: List[str] = []
        for mem in memories:
            formatted_parts.append(self._format_single_memory(mem))
            formatted_parts.append("")  # 每条记忆之间空一行

        result = "\n".join(formatted_parts).rstrip("\n")
        logger.info(f"格式化记忆文本完成 memory_count={len(memories)} text_length={len(result)}")
        return result
