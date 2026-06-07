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
        route = request.route
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

    async def retrieve_and_format_knowledge(
        self,
        query_text: str,
        query_vector: list[float],
        search_queries: list[str] | None = None,
        reference_time: str | None = None,
        temporal_deviation: int = 0,
        entity_mentions: list[str] | None = None,
    ) -> str:
        """
        检索外部知识库并格式化为可注入 Prompt 的文本。

        做什么：与长期记忆的 retrieve_and_format_memories 完全对齐的参数模式。
                底层通过 KnowledgeRetriever 按规则分配参数：
                - 向量检索：仅使用 search_queries（优先），降级到 [query_text]
                - BM25 检索：使用 entity_mentions + query_text + reference_time/temporal_deviation
                - query_text（即 disambiguated_text）作为基础查询贯穿所有策略
        返回：格式化的知识文本，每段以 [来源 N]: <文档名>\n<内容>\n 形式组织。
        """
        from app.rag.knowledge_retriever import KnowledgeRetriever

        retriever = KnowledgeRetriever(
            pg_repo=self.pg_repo,
            qdrant_repo=self.qdrant_repo,
            inference_svc=self.inference_svc,
            retrieval_top_k=20,
            rerank_top_k=3,
        )

        # 执行混合检索，传递所有精化参数
        candidates = await retriever.retrieve(
            query_text=query_text,
            search_mode="hybrid",
            search_queries=search_queries,
            reference_time=reference_time,
            temporal_deviation=temporal_deviation,
            entity_mentions=entity_mentions,
        )
        if not candidates:
            return ""

        # 格式化为可注入 Prompt 的文本
        parts: list[str] = []
        # 从 _build_evidences 借用重排逻辑以获得一致的 evidence 构建
        from app.rag.types import RagEvidence, RagSourceType

        for idx, (candidate, score) in enumerate(candidates, start=1):
            chunk = candidate.chunk
            document = candidate.document
            parts.append(f"[来源 {idx}]: {document.filename}")
            parts.append(chunk.content_text)
            parts.append("")  # 空行分隔

        result = "\n".join(parts).rstrip("\n")
        await self.event_publisher.publish_thought(query_text, "formatting", f"外部知识格式化完成，共 {len(candidates)} 条证据")
        logger.info(f"外部知识库检索格式化完成 hits={len(candidates)} text_length={len(result)}")
        return result

    async def _keyword_search(self, request: RagSearchRequest) -> list[ScoredCandidate]:
        """执行纯 BM25/FTS 关键词检索。"""
        from app.rag.knowledge_retriever import KnowledgeRetriever
        
        retriever = KnowledgeRetriever(
            pg_repo=self.pg_repo,
            qdrant_repo=self.qdrant_repo,
            inference_svc=self.inference_svc,
            retrieval_top_k=request.retrieval_top_k,
            rerank_top_k=request.retrieval_top_k # 内部重排数量与检索阶段对齐
        )
        
        candidates = await retriever.retrieve(
            query_text=request.query,
            search_mode="keyword",
            entity_mentions=None,
        )
        return [ScoredCandidate(candidate=c, score=s) for c, s in candidates]

    async def _hybrid_search(self, request: RagSearchRequest, trace_id: str) -> list[ScoredCandidate]:
        """执行并发 BM25 + Qdrant 向量召回，废弃 RRF 融合，统一使用 Reranker。"""
        await self.event_publisher.publish_thought(trace_id, "retrieving", "正在执行 BM25 与向量双路召回")
        
        from app.rag.knowledge_retriever import KnowledgeRetriever
        
        retriever = KnowledgeRetriever(
            pg_repo=self.pg_repo,
            qdrant_repo=self.qdrant_repo,
            inference_svc=self.inference_svc,
            retrieval_top_k=request.retrieval_top_k,
            rerank_top_k=request.retrieval_top_k
        )
        
        # 直接使用我们新编写的 knowledge_retriever 执行双路召回并由它完成内部 Reranker 操作，
        # 在这里我们由于是在 _hybrid_search 里，外部也会进行一次 rerank,
        # 所以我们返回所有通过初筛与内部 rerank 的 candidates 给外部使用。
        candidates = await retriever.retrieve(
            query_text=request.query,
            search_mode="hybrid",
        )
        return [ScoredCandidate(candidate=c, score=s) for c, s in candidates]

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
            
            # 使用 Small Model 评估证据充分性
            is_sufficient = await self._evaluate_evidence_sufficiency(request.query, candidates, trace_id)
            if is_sufficient:
                return candidates
                
            # 更新最佳候选项（如果当前结果比之前的结果更好）
            if len(candidates) > len(best_candidates):
                best_candidates = candidates
                
            # 重写查询以供下一轮使用
            if attempt < request.max_retries:
                 current_query = await self._rewrite_query_agentic(request.query, current_query, trace_id)
                 
        # 返回在所有尝试中找到的最佳候选项
        return best_candidates

    async def _evaluate_evidence_sufficiency(self, query: str, candidates: list[ScoredCandidate], trace_id: str) -> bool:
        """引入 Small Model 对检索证据进行动态打分评估。"""
        if not candidates:
            return False
            
        # 执行动态打分
        try:
            from app.api.internal_service import internal_service
            
            # 使用 LLM 对首个证据内容进行有效性评价
            content_to_evaluate = candidates[0].candidate.chunk.content_text
            prompt = f"请评估以下内容是否足以回答问题 '{query}'。只需返回 'YES' 或 'NO'。\n内容：{content_to_evaluate}"
            response = await internal_service.short_summarize(trace_id, prompt) # 复用内部轻量请求通道
            result = response[0] if isinstance(response, tuple) else response
            if result and "YES" in result.upper():
                return True
            return False
        except Exception as e:
            logger.warning(f"Agentic 证据充分性评估异常，降级为启发式评价 error={e}")
            return len(candidates) >= 3 and candidates[0].score >= 0.05

    async def _rewrite_query_agentic(self, original_query: str, current_query: str, trace_id: str) -> str:
        """使用 Small Model 进行 Query 重写。"""
        try:
            from app.api.internal_service import internal_service
            prompt = f"原问题：'{original_query}'。之前的检索词：'{current_query}'。检索结果不够好。请提供一个新的、更宽泛或不同视角的检索词，不要包含任何额外解释。"
            response = await internal_service.short_summarize(trace_id, prompt)
            new_query = response[0] if isinstance(response, tuple) else response
            if new_query and len(new_query.strip()) > 1:
                return new_query.strip()
        except Exception as e:
            logger.warning(f"Agentic Query重写异常，降级为启发式重写 error={e}")
            
        keywords = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_\-]{2,}", original_query)
        deduped = list(dict.fromkeys(keywords))
        if deduped:
            return " ".join(deduped[:8]) + " " + original_query
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
