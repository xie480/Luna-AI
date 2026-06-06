"""
Luna RAG 检索编排模块

做什么：实现 Keyword、Hybrid、Agentic 三路检索路由，包含 BM25、Qdrant、RRF、Rerank、父子扩展与 SSE 事件。
为什么这样做：废弃不可观测黑盒链路，用显式 Python 编排保证每一步可审计、可恢复、可解释。
输入输出：输入 RagSearchRequest，输出 RagSearchResponse 与可注入 Prompt 的证据上下文。
边界条件：低相关结果会被截断；Agentic 最多执行 max_retries 次重写回路。
异常行为：单路检索失败会记录日志并保留其它可用链路，全部失败时返回空证据而非伪造结果。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.logger import logger
from app.rag.types import RagEvidence, RagSearchRequest, RagSearchResponse
from app.repository.rag_pg import RagChunkCandidate, RagPGRepository
from app.repository.rag_qdrant import RagQdrantRepository, RagVectorHit
from app.types.constants import RAG_EVENT_CITATION, RAG_EVENT_THOUGHT, RagRetrievalRoute, RagSourceType


class RetrievalInferenceService(Protocol):
    """检索推理服务协议。"""

    async def get_embedding_vector(self, text: str) -> list[float]:
        """返回查询文本向量。"""

    async def rerank_documents(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        """返回包含 index 与 score 的重排结果。"""


class LLMRouterService(Protocol):
    """轻量 LLM 路由服务协议。"""

    async def structured_chat(self, prompt: str, trace_id: str) -> dict[str, Any]:
        """返回结构化 JSON 响应。"""


@dataclass(frozen=True)
class ScoredCandidate:
    """融合后的候选证据。"""

    candidate: RagChunkCandidate
    score: float


class RagEventPublisher:
    """
    RAG SSE 事件发布器。

    做什么：向现有 SSE 通道发布 EVT_RAG_THOUGHT 与 EVT_RAG_CITATION。
    为什么这样做：LangGraph/检索内部状态需要被前端观察，但不能让前端参与调度。
    """

    async def publish_thought(self, trace_id: str, stage: str, msg: str) -> None:
        """发布 RAG 思考链事件。"""
        from app.api.sse import sse_manager

        await sse_manager.publish({"type": RAG_EVENT_THOUGHT, "trace_id": trace_id, "payload": {"stage": stage, "msg": msg}})

    async def publish_citations(self, trace_id: str, citations: list[dict[str, Any]]) -> None:
        """发布 RAG 引用事件。"""
        from app.api.sse import sse_manager

        await sse_manager.publish({"type": RAG_EVENT_CITATION, "trace_id": trace_id, "payload": citations})


class RagRetrievalOrchestrator:
    """
    RAG 多路检索编排器。

    做什么：根据查询意图选择关键词、混合或 Agentic 反思检索链路。
    为什么这样做：单次向量检索对跳跃问题脆弱，多路路由能在性能和精度之间显式取舍。
    """

    def __init__(
        self,
        pg_repo: RagPGRepository,
        qdrant_repo: RagQdrantRepository | None,
        inference_svc: RetrievalInferenceService | None,
        event_publisher: RagEventPublisher | None = None,
    ) -> None:
        self.pg_repo = pg_repo
        self.qdrant_repo = qdrant_repo
        self.inference_svc = inference_svc
        self.event_publisher = event_publisher or RagEventPublisher()

    async def search(self, request: RagSearchRequest, trace_id: str) -> RagSearchResponse:
        """执行完整检索编排。"""
        route = request.route or self._route_query(request.query)
        await self.event_publisher.publish_thought(trace_id, "routing", f"已选择 RAG 检索链路: {route.value}")
        if route == RagRetrievalRoute.KEYWORD:
            candidates = await self._keyword_search(request)
        elif route == RagRetrievalRoute.AGENTIC:
            candidates = await self._agentic_search(request, trace_id)
        else:
            candidates = await self._hybrid_search(request, trace_id)
        evidences = await self._build_evidences(request.query, candidates, request.rerank_top_k)
        prompt_context = self._format_prompt_context(evidences)
        citations = [
            {
                "id": evidence.citation_id,
                "doc": evidence.document_name,
                "chunk": evidence.chunk_id,
                "score": evidence.score,
            }
            for evidence in evidences
        ]
        await self.event_publisher.publish_citations(trace_id, citations)
        return RagSearchResponse(route=route, evidences=evidences, prompt_context=prompt_context, citations=citations)

    def _route_query(self, query: str) -> RagRetrievalRoute:
        """基于可解释启发式选择检索链路。"""
        stripped = query.strip()
        if re.search(r"[`{}()\[\]=]|错误|报错|日志|函数|类|配置项", stripped):
            return RagRetrievalRoute.KEYWORD
        if len(stripped) > 80 or any(mark in stripped for mark in ("为什么", "如何", "对比", "分别", "步骤")):
            return RagRetrievalRoute.AGENTIC
        return RagRetrievalRoute.HYBRID

    async def _keyword_search(self, request: RagSearchRequest) -> list[ScoredCandidate]:
        """执行纯 BM25/FTS 关键词检索。"""
        candidates = await self.pg_repo.search_by_text(request.query, request.retrieval_top_k)
        return [ScoredCandidate(candidate=item, score=item.score) for item in candidates]

    async def _hybrid_search(self, request: RagSearchRequest, trace_id: str) -> list[ScoredCandidate]:
        """执行 BM25 + Qdrant 向量双路召回并通过 RRF 融合。"""
        await self.event_publisher.publish_thought(trace_id, "retrieving", "正在执行 BM25 与向量双路召回")
        keyword_task = asyncio.create_task(self.pg_repo.search_by_text(request.query, request.retrieval_top_k))
        vector_task = asyncio.create_task(self._vector_search(request.query, request.retrieval_top_k))
        keyword_candidates, vector_candidates = await asyncio.gather(keyword_task, vector_task)
        return self._rrf_fuse(keyword_candidates, vector_candidates, request.alpha)

    async def _agentic_search(self, request: RagSearchRequest, trace_id: str) -> list[ScoredCandidate]:
        """
        执行有限次查询重写与自评估检索回路。
        
        该方法通过多轮迭代尝试改进查询结果，每轮都会评估当前结果的相关性，
        如果结果足够好则直接返回，否则继续重写查询并尝试下一轮检索。
        
        参数:
            request (RagSearchRequest): RAG搜索请求对象，包含原始查询和其他配置参数
            trace_id (str): 追踪ID，用于追踪整个搜索过程
            
        返回:
            list[ScoredCandidate]: 包含评分的候选结果列表，按相关性排序
        """
        # 初始化当前查询为原始请求中的查询
        current_query = request.query
        # 存储最佳的候选项结果
        best_candidates: list[ScoredCandidate] = []
        # 根据最大重试次数进行循环
        for attempt in range(request.max_retries + 1):
            # 发布当前思考状态到事件发布器
            await self.event_publisher.publish_thought(
                trace_id,
                "evaluating",
                f"正在执行第 {attempt + 1} 轮证据检索与相关性审查",
            )
            # 创建嵌套请求，使用当前查询和混合检索路由
            nested_request = request.model_copy(update={"query": current_query, "route": RagRetrievalRoute.HYBRID})
            # 执行混合搜索获取候选结果
            candidates = await self._hybrid_search(nested_request, trace_id)
            # 检查当前检索到的证据是否足够
            if self._is_evidence_sufficient(candidates):
                return candidates
            # 更新最佳候选项（如果当前结果比之前的结果更好）
            if len(candidates) > len(best_candidates):
                best_candidates = candidates
            # 重写查询以供下一轮使用
            current_query = self._rewrite_query(request.query, current_query, attempt)
        # 返回在所有尝试中找到的最佳候选项
        return best_candidates

    async def _vector_search(self, query: str, top_k: int) -> list[tuple[RagChunkCandidate, float]]:
        """执行向量检索并回表取正文。"""
        if self.qdrant_repo is None or self.inference_svc is None:
            return []
        try:
            query_vector = await self.inference_svc.get_embedding_vector(query)
            vector_hits = await self.qdrant_repo.search(query_vector, top_k)
            candidates = await self.pg_repo.get_chunks_by_ids([hit.chunk_id for hit in vector_hits])
            hit_scores = {hit.chunk_id: hit.score for hit in vector_hits}
            return [(candidate, hit_scores.get(candidate.chunk.chunk_id, 0.0)) for candidate in candidates]
        except Exception as exc:
            logger.warning(f"RAG 向量检索失败，将仅使用稀疏检索 error={exc}")
            return []

    def _rrf_fuse(
        self,
        keyword_candidates: list[RagChunkCandidate],
        vector_candidates: list[tuple[RagChunkCandidate, float]],
        alpha: float,
    ) -> list[ScoredCandidate]:
        """
        使用 Reciprocal Rank Fusion 融合稀疏与稠密结果。
        
        参数:
            keyword_candidates (list[RagChunkCandidate]): 关键词检索得到的候选结果列表
            vector_candidates (list[tuple[RagChunkCandidate, float]]): 向量检索得到的候选结果及对应分数的元组列表
            alpha (float): 控制向量检索结果权重的系数，范围通常在 [0, 1] 之间，0 表示只考虑关键词结果，1 表示只考虑向量结果
            
        返回:
            list[ScoredCandidate]: 融合后的带评分候选结果列表，按分数降序排列
        """
        # 设置 RRF 公式中的平滑常数 k，默认为 60.0
        k = 60.0
        
        # 存储每个 chunk_id 对应的融合得分
        score_map: dict[str, float] = {}
        
        # 存储每个 chunk_id 对应的候选对象，便于后续构建结果
        candidate_map: dict[str, RagChunkCandidate] = {}
        
        # 处理关键词检索结果，计算其在 RRF 融合中的贡献分数
        for rank, candidate in enumerate(keyword_candidates, start=1):
            chunk_id = candidate.chunk.chunk_id
            candidate_map[chunk_id] = candidate
            # 计算关键词检索部分的 RRF 分数，使用 (1.0 - alpha) 作为权重
            score_map[chunk_id] = score_map.get(chunk_id, 0.0) + (1.0 - alpha) / (k + rank)
            
        # 处理向量检索结果，计算其在 RRF 融合中的贡献分数
        for rank, (candidate, vector_score) in enumerate(vector_candidates, start=1):
            chunk_id = candidate.chunk.chunk_id
            candidate_map[chunk_id] = candidate
            # 计算向量检索部分的 RRF 分数，使用 alpha 作为权重，并加上原始向量分数的小比例（0.001）作为微调
            score_map[chunk_id] = score_map.get(chunk_id, 0.0) + alpha / (k + rank) + vector_score * 0.001
            
        # 将融合后的得分和对应的候选对象组装成 ScoredCandidate 对象列表
        fused = [ScoredCandidate(candidate=candidate_map[chunk_id], score=score) for chunk_id, score in score_map.items()]
        
        # 按照得分从高到低排序，确保最相关的候选结果排在前面
        fused.sort(key=lambda item: item.score, reverse=True)
        return fused

    def _is_evidence_sufficient(self, candidates: list[ScoredCandidate]) -> bool:
        """用可解释阈值判断证据是否足够。"""
        if len(candidates) >= 3:
            return True
        return bool(candidates and candidates[0].score >= 0.05)

    def _rewrite_query(self, original_query: str, current_query: str, attempt: int) -> str:
        """生成下一轮检索查询，避免依赖不可控黑盒重写。"""
        keywords = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_\-]{2,}", original_query)
        deduped = list(dict.fromkeys(keywords))
        if attempt % 2 == 0 and deduped:
            return " ".join(deduped[:8])
        return f"{current_query} {original_query}"

    async def _build_evidences(
        self,
        query: str,
        candidates: list[ScoredCandidate],
        top_k: int,
    ) -> list[RagEvidence]:
        """
        构建证据列表，对候选结果进行重排、父子文档扩展，并转换为可引用的证据格式。
        
        参数:
            query (str): 检索查询字符串
            candidates (list[ScoredCandidate]): 待处理的候选结果列表，包含得分信息
            top_k (int): 需要保留的顶级结果数量
        
        返回:
            list[RagEvidence]: 处理后的证据列表，每个证据包含引用ID、文档信息、内容等
        """
        # 如果没有候选结果，直接返回空列表
        if not candidates:
            return []
        
        # 对候选结果进行重排，选择top_k个最佳结果
        reranked = await self._rerank(query, candidates, top_k)
        
        # 提取所有有父文档ID的候选结果的父ID
        parent_ids = [item.candidate.chunk.parent_id for item in reranked if item.candidate.chunk.parent_id]
        
        # 根据父文档ID获取对应的父文档内容
        parent_map = await self.pg_repo.get_parent_chunks(parent_ids)
        
        # 初始化证据列表
        evidences: list[RagEvidence] = []
        
        # 遍历重排后的结果，构建最终的证据对象
        for index, item in enumerate(reranked, start=1):
            chunk = item.candidate.chunk
            document = item.candidate.document
            content = chunk.content_text
            
            # 如果当前块有父文档且在父文档映射中存在，则使用父文档的内容
            if chunk.parent_id and chunk.parent_id in parent_map:
                content = parent_map[chunk.parent_id].content_text
            
            # 创建RagEvidence对象并添加到证据列表
            evidences.append(
                RagEvidence(
                    citation_id=index,  # 引用ID，从1开始递增
                    document_id=document.id,  # 文档唯一标识符
                    document_name=document.filename,  # 文档名称
                    chunk_id=chunk.chunk_id,  # 块唯一标识符
                    parent_id=chunk.parent_id,  # 父文档ID
                    content=content,  # 内容文本（可能来自父文档）
                    score=max(item.score, 0.0),  # 得分，确保非负
                    source_type=RagSourceType(document.source_type),  # 源类型
                    metadata=chunk.meta_payload or {},  # 元数据，如果为空则使用空字典
                )
            )
        return evidences

    async def _rerank(self, query: str, candidates: list[ScoredCandidate], top_k: int) -> list[ScoredCandidate]:
        """使用 CrossEncoder 重排，失败时按融合分降级。"""
        sorted_candidates = sorted(candidates, key=lambda item: item.score, reverse=True)
        if self.inference_svc is None or len(sorted_candidates) <= 1:
            return sorted_candidates[:top_k]
        docs = [item.candidate.chunk.content_text for item in sorted_candidates]
        try:
            rerank_results = await self.inference_svc.rerank_documents(query, docs)
            reranked: list[ScoredCandidate] = []
            for result in rerank_results[:top_k]:
                index = int(result.get("index", 0))
                if 0 <= index < len(sorted_candidates):
                    reranked.append(
                        ScoredCandidate(
                            candidate=sorted_candidates[index].candidate,
                            score=float(result.get("score", sorted_candidates[index].score)),
                        )
                    )
            return reranked
        except Exception as exc:
            logger.warning(f"RAG Rerank 失败，使用融合分截断 error={exc}")
            return sorted_candidates[:top_k]

    @staticmethod
    def _format_prompt_context(evidences: list[RagEvidence]) -> str:
        """格式化 Prompt 证据上下文。"""
        parts: list[str] = []
        for evidence in evidences:
            parts.append(
                f"[引用 {evidence.citation_id}] 文档: {evidence.document_name} "
                f"chunk_id={evidence.chunk_id}\n{evidence.content}"
            )
        return "\n\n".join(parts)
