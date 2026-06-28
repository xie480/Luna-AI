"""Agent Loop 资源分级加载服务。

做什么：根据资源文件大小自动选择加载策略（Tier 1/2/3），
        小资源全量加载保证完整性，大资源向量检索控制 Token 消耗。
为什么这样做：不同大小的资源需要不同的加载策略，
              避免大资源全量注入导致上下文溢出或注意力丢失。
输入输出：
    - ResourceTierService: 资源分级加载服务类
    - load_resource(): 根据资源定义和 query 文本执行分级加载
边界条件：
    - Qdrant 不可用时降级为 Tier 1 全量加载
    - 文件不存在时记录错误并返回空结果
    - Embedding 服务不可用时降级为 Tier 1
异常行为：
    - 单个资源加载失败不终止流程，记录错误后继续
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.logger import logger


# Qdrant 集合名称常量
QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS = "skill_resource_chunks"

# 向量维度（与现有 RAG embedding 模型一致）
DEFAULT_VECTOR_SIZE = 1024


class ResourceLoadResult:
    """资源加载结果。

    做什么：封装单次资源加载的完整结果，包括内容、分层策略和元数据。
    为什么这样做：统一返回结构，方便 ResourceLoadNode 写入 loaded_resources。
    """

    def __init__(
        self,
        resource_name: str,
        content: str = "",
        success: bool = True,
        tier_used: str = "tier1_full",
        chunk_count: int = 0,
        error_message: str = "",
    ) -> None:
        self.resource_name = resource_name
        self.content = content
        self.success = success
        self.tier_used = tier_used
        self.chunk_count = chunk_count
        self.error_message = error_message


class ResourceTierService:
    """资源分级加载服务。

    做什么：根据资源文件大小自动选择加载策略（Tier 1/2/3）。
    为什么这样做：不同大小的资源需要不同的加载策略，
                  小资源全量加载保证完整性，大资源检索加载控制 Token 消耗。
    分级策略：
        Tier 1: ≤ 4096 token → 全量加载
        Tier 2: 4K ~ 20K token → 单 query 向量检索 top_k=5
        Tier 3: > 20K token → 多 query 检索 + 轻精排 top_k=8→5
    """

    # === 分级阈值（token 数）===
    # 为什么这样做：模型上下文长度为 1M token，因此阈值可以大幅放宽。
    # Tier 1（≤50K token）：绝大多数资源文件都在此范围，全量加载即可。
    # Tier 2（50K~200K token）：中大型文档，单 query 向量检索。
    # Tier 3（>200K token）：超大知识库，多 query + 轻精排。
    TIER1_MAX_TOKENS: int = 50000
    TIER2_MAX_TOKENS: int = 200000

    # === 检索参数 ===
    TIER2_TOP_K: int = 10
    TIER3_TOP_K: int = 15
    TIER3_FINAL_TOP_K: int = 10
    SIMILARITY_THRESHOLD_TIER2: float = 0.60
    SIMILARITY_THRESHOLD_TIER3: float = 0.55

    # === chunk 参数 ===
    CHUNK_SIZE_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64

    # === 相似去重阈值 ===
    DEDUP_THRESHOLD: float = 0.9

    def __init__(
        self,
        qdrant_client: Any | None = None,
        embedding_service: Any | None = None,
        skill_registry: Any | None = None,
    ) -> None:
        """初始化资源分级加载服务。

        参数:
            qdrant_client: Qdrant 客户端包装器（QdrantClientWrapper 实例）。
                           为 None 时 Tier 2/3 降级为 Tier 1。
            embedding_service: Embedding 推理服务（需实现 get_embedding_vector(text)）。
                               为 None 时 Tier 2/3 降级为 Tier 1。
            skill_registry: SkillRegistry 实例，用于读取资源文件内容。
        """
        self.qdrant_client = qdrant_client
        self.embedding_service = embedding_service
        self.skill_registry = skill_registry

    async def load_resource(
        self,
        trace_id: str,
        resource_def: dict[str, Any],
        query_texts: list[str],
        step_intent: str = "",
    ) -> ResourceLoadResult:
        """分级加载资源入口。

        做什么：
        1. 读取资源文件，估算 token 数
        2. 根据 token 数选择 Tier 策略
        3. 执行加载，返回结果

        参数:
            trace_id: 追踪 ID。
            resource_def: 资源定义（name, resource_type, uri, description）。
            query_texts: 检索 query 列表（Tier 2/3 使用）。
            step_intent: 当前步骤意图（Tier 3 轻精排使用）。
        返回:
            ResourceLoadResult: 加载结果。
        边界条件：
            - resource_def 为空时返回失败结果。
            - 文件不存在时记录错误并返回失败结果。
        """
        resource_name = resource_def.get("name", "")
        resource_uri = resource_def.get("uri", "")

        if not resource_name:
            logger.warning(f"[TraceID:{trace_id}] 资源定义缺少 name 字段: {resource_def}")
            return ResourceLoadResult(
                resource_name="",
                success=False,
                error_message="资源定义缺少 name 字段",
            )

        # 读取资源文件内容
        raw_content = await self._read_resource_file(trace_id, resource_def)
        if raw_content is None:
            return ResourceLoadResult(
                resource_name=resource_name,
                success=False,
                tier_used="tier1_full",
                error_message=f"资源文件读取失败: {resource_uri}",
            )

        # 估算 token 数
        estimated_tokens = self._estimate_tokens(raw_content)
        logger.info(
            f"[TraceID:{trace_id}] 资源 {resource_name}: "
            f"文件大小 {len(raw_content)} 字符, "
            f"估算 {estimated_tokens} token"
        )

        # 根据 token 数选择 Tier 策略
        if estimated_tokens <= self.TIER1_MAX_TOKENS:
            # Tier 1: 小文件全量加载
            return await self._tier1_full_load(trace_id, resource_name, raw_content)

        # 需要向量检索（Tier 2 或 Tier 3）
        # 检查 Qdrant 和 Embedding 服务是否可用
        if not self._can_use_vector_search():
            logger.warning(
                f"[TraceID:{trace_id}] 资源 {resource_name}: "
                f"Qdrant 或 Embedding 服务不可用，降级为 Tier 1 全量加载"
            )
            return await self._tier1_full_load(trace_id, resource_name, raw_content)

        if estimated_tokens <= self.TIER2_MAX_TOKENS:
            # Tier 2: 中等文件单 query 向量检索
            return await self._tier2_vector_search(
                trace_id, resource_def, query_texts, step_intent
            )

        # Tier 3: 大文件多 query 检索 + 轻精排
        return await self._tier3_multi_query_search(
            trace_id, resource_def, query_texts, step_intent
        )

    async def _read_resource_file(
        self, trace_id: str, resource_def: dict[str, Any]
    ) -> str | None:
        """读取资源文件内容。

        做什么：通过 skill_registry 读取资源文件的原始内容。
        参数:
            trace_id: 追踪 ID。
            resource_def: 资源定义字典。
        返回:
            文件内容字符串，读取失败返回 None。
        """
        resource_name = resource_def.get("name", "")
        resource_uri = resource_def.get("uri", "")
        resource_type = resource_def.get("resource_type", "file")

        try:
            # 优先通过 skill_registry 加载
            if self.skill_registry and hasattr(self.skill_registry, "load_resource_file"):
                content = await self.skill_registry.load_resource_file(
                    resource_uri=resource_uri,
                    resource_type=resource_type,
                )
                if content:
                    return content

            # 兜底：直接读取文件（仅限 file 类型且 uri 为本地路径）
            if resource_type == "file" and resource_uri:
                # 处理相对路径（相对于 ai-service 根目录）
                if not os.path.isabs(resource_uri):
                    base_dir = os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    )
                    resource_uri = os.path.join(base_dir, resource_uri)

                if os.path.exists(resource_uri):
                    with open(resource_uri, encoding="utf-8") as f:
                        return f.read()

            logger.warning(
                f"[TraceID:{trace_id}] 资源文件不可读取: "
                f"name={resource_name}, uri={resource_def.get('uri', '')}, "
                f"type={resource_type}"
            )
            return None

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] 资源文件读取异常: "
                f"name={resource_name}, error={exc}"
            )
            return None

    async def _tier1_full_load(
        self,
        trace_id: str,
        resource_name: str,
        raw_content: str,
    ) -> ResourceLoadResult:
        """Tier 1: 全量加载。

        做什么：直接返回文件全部内容。
        为什么这样做：小文件全量加载信息完整，不会断章取义。
        参数:
            trace_id: 追踪 ID。
            resource_name: 资源名称。
            raw_content: 文件原始内容。
        返回:
            ResourceLoadResult: 包含完整文件内容的加载结果。
        """
        logger.info(
            f"[TraceID:{trace_id}] Tier 1 全量加载: "
            f"resource={resource_name}, size={len(raw_content)} 字符"
        )
        return ResourceLoadResult(
            resource_name=resource_name,
            content=raw_content,
            success=True,
            tier_used="tier1_full",
        )

    async def _tier2_vector_search(
        self,
        trace_id: str,
        resource_def: dict[str, Any],
        query_texts: list[str],
        step_intent: str = "",
    ) -> ResourceLoadResult:
        """Tier 2: 单 query 向量检索。

        做什么：使用第一个 query 文本做向量检索，取 top_k 结果。
        参数:
            trace_id: 追踪 ID。
            resource_def: 资源定义。
            query_texts: 检索 query 列表。
            step_intent: 当前步骤意图。
        返回:
            ResourceLoadResult: 包含检索结果的加载结果。
        """
        resource_name = resource_def.get("name", "")
        resource_id = resource_def.get("id", "")
        query_text = query_texts[0] if query_texts else resource_name

        try:
            # 生成 query 向量
            query_vector = await self.embedding_service.get_embedding_vector(query_text)

            # 在 Qdrant 中检索
            search_results = await self.qdrant_client.search(
                collection_name=QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS,
                query_vector=query_vector,
                limit=self.TIER2_TOP_K,
                score_threshold=self.SIMILARITY_THRESHOLD_TIER2,
                query_filter={
                    "must": [
                        {"key": "resource_name", "match": {"value": resource_name}},
                    ]
                },
            )

            if not search_results:
                logger.warning(
                    f"[TraceID:{trace_id}] Tier 2 检索无结果: "
                    f"resource={resource_name}, query={query_text[:50]}"
                )
                # 降级：使用资源描述作为兜底
                description = resource_def.get("description", "")
                return ResourceLoadResult(
                    resource_name=resource_name,
                    content=description if description else "",
                    success=True,
                    tier_used="tier2_vector_search_empty",
                )

            # 合并检索结果
            chunks = []
            for result in search_results:
                payload = result.payload if hasattr(result, "payload") else {}
                chunk_text = payload.get("chunk_text", "")
                if chunk_text:
                    chunks.append(chunk_text)

            content = "\n\n---\n\n".join(chunks)

            logger.info(
                f"[TraceID:{trace_id}] Tier 2 向量检索完成: "
                f"resource={resource_name}, "
                f"结果数={len(chunks)}, "
                f"总长度={len(content)} 字符"
            )

            return ResourceLoadResult(
                resource_name=resource_name,
                content=content,
                success=True,
                tier_used="tier2_vector_search",
                chunk_count=len(chunks),
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] Tier 2 向量检索异常: "
                f"resource={resource_name}, error={exc}"
            )
            # 降级：尝试全量加载
            return await self._fallback_to_full_load(trace_id, resource_def)

    async def _tier3_multi_query_search(
        self,
        trace_id: str,
        resource_def: dict[str, Any],
        query_texts: list[str],
        step_intent: str = "",
    ) -> ResourceLoadResult:
        """Tier 3: 多 query 检索 + 轻精排。

        做什么：使用多个 query 文本分别检索，合并结果后做轻精排。
        参数:
            trace_id: 追踪 ID。
            resource_def: 资源定义。
            query_texts: 检索 query 列表（通常 3~5 个）。
            step_intent: 当前步骤意图（轻精排使用）。
        返回:
            ResourceLoadResult: 包含精排结果的加载结果。
        """
        resource_name = resource_def.get("name", "")

        if not query_texts:
            query_texts = [resource_name]

        try:
            # 收集所有 query 的检索结果
            all_chunks: list[dict[str, Any]] = []
            seen_chunk_ids: set[str] = set()

            for query_text in query_texts:
                query_vector = await self.embedding_service.get_embedding_vector(query_text)

                search_results = await self.qdrant_client.search(
                    collection_name=QDRANT_COLLECTION_SKILL_RESOURCE_CHUNKS,
                    query_vector=query_vector,
                    limit=self.TIER3_TOP_K,
                    score_threshold=self.SIMILARITY_THRESHOLD_TIER3,
                    query_filter={
                        "must": [
                            {"key": "resource_name", "match": {"value": resource_name}},
                        ]
                    },
                )

                for result in search_results:
                    result_id = str(result.id) if hasattr(result, "id") else ""
                    if result_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(result_id)

                    payload = result.payload if hasattr(result, "payload") else {}
                    chunk_text = payload.get("chunk_text", "")
                    if chunk_text:
                        all_chunks.append({
                            "chunk_text": chunk_text,
                            "score": result.score if hasattr(result, "score") else 0.0,
                            "chunk_index": payload.get("chunk_index", 0),
                            "section_title": payload.get("section_title", ""),
                            "char_offset_start": payload.get("char_offset_start", 0),
                            "query_hit_count": 1,
                        })

            if not all_chunks:
                logger.warning(
                    f"[TraceID:{trace_id}] Tier 3 多 query 检索无结果: "
                    f"resource={resource_name}"
                )
                description = resource_def.get("description", "")
                return ResourceLoadResult(
                    resource_name=resource_name,
                    content=description if description else "",
                    success=True,
                    tier_used="tier3_multi_query_empty",
                )

            # 轻精排
            ranked_chunks = self._light_rerank(
                chunks=all_chunks,
                query_texts=query_texts,
                step_intent=step_intent,
                final_top_k=self.TIER3_FINAL_TOP_K,
            )

            # 相似去重
            deduped_chunks = self._deduplicate_chunks(ranked_chunks, self.DEDUP_THRESHOLD)

            # 取前 final_top_k 个
            final_chunks = deduped_chunks[:self.TIER3_FINAL_TOP_K]

            # 合并内容
            content = "\n\n---\n\n".join(
                chunk.get("chunk_text", "") for chunk in final_chunks
            )

            logger.info(
                f"[TraceID:{trace_id}] Tier 3 多 query 检索完成: "
                f"resource={resource_name}, "
                f"原始 chunk 数={len(all_chunks)}, "
                f"精排后={len(ranked_chunks)}, "
                f"去重后={len(deduped_chunks)}, "
                f"最终={len(final_chunks)}, "
                f"总长度={len(content)} 字符"
            )

            return ResourceLoadResult(
                resource_name=resource_name,
                content=content,
                success=True,
                tier_used="tier3_multi_query_rerank",
                chunk_count=len(final_chunks),
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] Tier 3 多 query 检索异常: "
                f"resource={resource_name}, error={exc}"
            )
            # 降级：尝试全量加载
            return await self._fallback_to_full_load(trace_id, resource_def)

    def _light_rerank(
        self,
        chunks: list[dict[str, Any]],
        query_texts: list[str],
        step_intent: str,
        final_top_k: int,
    ) -> list[dict[str, Any]]:
        """轻精排：纯规则排序，无重模型。

        做什么：对检索结果按 6 条规则进行综合评分排序。
        规则优先级：
            1. query 命中数（被越多 query 命中排名越高）
            2. 词重叠度（chunk 与 step_intent 的关键词重叠比例）
            3. 标题权重（所在章节标题匹配度）
            4. 位置权重（文档头部/尾部权重更高）
            5. 长度惩罚（过短 < 50 字或过长 > 2000 字的 chunk 降权）
            6. 相似去重（相似度 > 0.9 只保留一个）
        参数:
            chunks: 检索结果列表，每个 dict 至少含 chunk_text。
            query_texts: 所有 query 文本。
            step_intent: 当前步骤意图。
            final_top_k: 最终保留的 chunk 数。
        返回:
            排序后的 chunk 列表。
        """
        if not chunks:
            return []

        # 提取 step_intent 关键词集合（用于词重叠度计算）
        intent_keywords = self._extract_keywords(step_intent)
        # 提取所有 query 关键词集合（用于标题权重计算）
        all_query_keywords = set()
        for qt in query_texts:
            all_query_keywords.update(self._extract_keywords(qt))

        for chunk in chunks:
            score = 0.0
            chunk_text = chunk.get("chunk_text", "")
            section_title = chunk.get("section_title", "")
            chunk_index = chunk.get("chunk_index", 0)

            # 规则 1: query 命中数（权重 0.30）
            # 被越多 query 命中的 chunk 排名越高
            score += chunk.get("query_hit_count", 1) * 0.30

            # 规则 2: 词重叠度（权重 0.25）
            # chunk 与 step_intent 的关键词重叠比例
            chunk_keywords = self._extract_keywords(chunk_text)
            if intent_keywords and chunk_keywords:
                overlap = len(intent_keywords & chunk_keywords) / len(intent_keywords)
                score += overlap * 0.25

            # 规则 3: 标题权重（权重 0.20）
            # 所在章节标题匹配度
            if section_title:
                title_keywords = self._extract_keywords(section_title)
                if all_query_keywords and title_keywords:
                    title_overlap = len(all_query_keywords & title_keywords) / len(all_query_keywords)
                    score += title_overlap * 0.20

            # 规则 4: 位置权重（权重 0.10）
            # 文档头部/尾部的 chunk 权重更高
            total_chunks = max(chunk.get("_total_chunks", chunk_index + 1), 1)
            position_ratio = chunk_index / total_chunks
            # 头部 20% 和尾部 20% 获得加分
            if position_ratio <= 0.2 or position_ratio >= 0.8:
                score += 0.10

            # 规则 5: 长度惩罚（权重 0.15）
            # 过短（< 50 字）或过长（> 2000 字）的 chunk 降权
            text_len = len(chunk_text)
            if text_len < 50:
                score -= 0.15
            elif text_len > 2000:
                score -= 0.10
            else:
                score += 0.15

            chunk["_rerank_score"] = score

        # 按综合分数降序排列
        chunks.sort(key=lambda c: c.get("_rerank_score", 0), reverse=True)

        return chunks[:final_top_k]

    def _extract_keywords(self, text: str) -> set[str]:
        """从文本中提取关键词集合。

        做什么：分词并去停用词，提取有实际含义的词。
        实现：简单的基于正则的分词（中文逐字 + 英文按词）。
        参数:
            text: 输入文本。
        返回:
            关键词集合。
        """
        if not text:
            return set()
        # 英文单词
        english_words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))
        # 中文字符（逐字）
        chinese_chars = set(re.findall(r"[\u4e00-\u9fff]", text))
        return english_words | chinese_chars

    def _deduplicate_chunks(
        self,
        chunks: list[dict[str, Any]],
        threshold: float = 0.9,
    ) -> list[dict[str, Any]]:
        """相似 chunk 去重。

        做什么：使用 Jaccard 相似度去除高度相似的 chunk，只保留第一个。
        为什么这样做：多 query 检索可能召回内容重叠的 chunk，去重避免冗余。
        参数:
            chunks: chunk 列表（已排序）。
            threshold: Jaccard 相似度阈值，超过此值视为重复。
        返回:
            去重后的 chunk 列表。
        """
        if not chunks:
            return []

        deduped: list[dict[str, Any]] = []
        kept_keyword_sets: list[set[str]] = []

        for chunk in chunks:
            chunk_text = chunk.get("chunk_text", "")
            chunk_keywords = self._extract_keywords(chunk_text)

            # 检查是否与已保留的 chunk 相似
            is_duplicate = False
            for kept_set in kept_keyword_sets:
                if not chunk_keywords or not kept_set:
                    continue
                union_size = len(chunk_keywords | kept_set)
                if union_size == 0:
                    continue
                jaccard = len(chunk_keywords & kept_set) / union_size
                if jaccard > threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                deduped.append(chunk)
                kept_keyword_sets.append(chunk_keywords)

        return deduped

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数。

        做什么：基于字符类型估算 token 数。
        规则：中文约 1.5 字/token（约 0.67 token/字），英文约 4 字符/token。
        参数:
            text: 输入文本。
        返回:
            估算的 token 数。
        """
        if not text:
            return 0

        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        other_chars = len(text) - chinese_chars

        # 中文：约 0.67 token/字，英文：约 0.25 token/字符
        estimated = int(chinese_chars * 0.67 + other_chars * 0.25)
        return max(estimated, 1)

    def _can_use_vector_search(self) -> bool:
        """判断是否可以使用向量检索。

        做什么：检查 Qdrant 客户端和 Embedding 服务是否可用。
        返回:
            True 表示可以使用向量检索，False 需要降级。
        """
        return self.qdrant_client is not None and self.embedding_service is not None

    async def _fallback_to_full_load(
        self,
        trace_id: str,
        resource_def: dict[str, Any],
    ) -> ResourceLoadResult:
        """降级：全量加载。

        做什么：当向量检索失败时，尝试读取文件全量内容作为降级方案。
        参数:
            trace_id: 追踪 ID。
            resource_def: 资源定义。
        返回:
            ResourceLoadResult: 降级后的加载结果。
        """
        resource_name = resource_def.get("name", "")
        raw_content = await self._read_resource_file(trace_id, resource_def)

        if raw_content is not None:
            logger.info(
                f"[TraceID:{trace_id}] 降级为 Tier 1 全量加载: "
                f"resource={resource_name}, size={len(raw_content)} 字符"
            )
            return ResourceLoadResult(
                resource_name=resource_name,
                content=raw_content,
                success=True,
                tier_used="tier1_fallback",
            )

        # 文件也读不了，返回描述兜底
        description = resource_def.get("description", "")
        logger.warning(
            f"[TraceID:{trace_id}] 降级全量加载也失败，使用 description 兜底: "
            f"resource={resource_name}"
        )
        return ResourceLoadResult(
            resource_name=resource_name,
            content=description,
            success=True,
            tier_used="description_fallback",
        )
