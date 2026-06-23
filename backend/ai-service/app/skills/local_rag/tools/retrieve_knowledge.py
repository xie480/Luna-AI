"""
MCP 工具：知识库 RAG 检索。

做什么：从导入的知识库文档中检索相关信息，支持多个查询词并行向量检索
       和时间范围约束的 BM25 关键词检索。底层委托 rag_orchestrator 的
       KnowledgeRetriever 做混合检索（向量稠密 + PG FTS 稀疏）+ Rerank。
风险等级：L0（低危，只读检索，无副作用）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.logger import logger

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query_text": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
            "minItems": 1,
            "maxItems": 5,
            "description": (
                "检索查询文本数组。每个元素为一个独立的查询词，"
                "用于向量语义检索。系统将对每个查询词并行执行"
                " Embedding + Qdrant 向量检索后合并去重。"
                "例如：['公司2023年营收数据', '公司2024年利润率']。"
            ),
        },
        "reference_time": {
            "type": "string",
            "description": (
                "BM25 检索的时间约束，ISO 8601 格式。"
                "用于在关键词检索结果中按文档创建时间做时间过滤。"
                "留空表示不限时间。"
                "例如：'2024-06-15T10:00:00+08:00'。"
            ),
            "default": "",
        },
        "temporal_deviation": {
            "type": "integer",
            "description": (
                "BM25 时间过滤允许的偏差天数。"
                "0 表示精确匹配当天，1 表示前后各 1 天，依此类推。"
                "最大不超过 7。默认 0。"
            ),
            "default": 0,
            "minimum": 0,
            "maximum": 7,
        },
    },
    "required": ["query_text"],
}


async def handle_retrieve_knowledge(
    parameters: dict[str, Any],
    trace_id: str,
    state_context: dict[str, Any] | None = None,
) -> str:
    """执行知识库 RAG 混合检索（多查询词并行向量 + 时间约束 BM25）。

    做什么：
      1. 向量稠密检索：对 query_text 数组中的每个查询词并行执行
         Embedding + Qdrant 向量检索，作为 search_queries 传入。
      2. BM25 稀疏检索：使用 reference_time 和 temporal_deviation
         在 PG FTS 结果中做时间过滤。
      3. 两路结果合并去重后经 CrossEncoder Rerank 重排。
    参数:
        parameters: 包含 query_text（必填）、reference_time（可选）、
                    temporal_deviation（可选）的字典。
        trace_id: 全链路追踪 ID。
        state_context: 运行时上下文，需包含 rag_orchestrator 和 session_id。
    返回:
        str: 检索到的知识库文档片段汇总文本（含引用来源）。
    异常行为：
        rag_orchestrator 不存在时返回错误提示文本。
        检索过程异常时返回错误描述文本。
    """
    query_text_list: list[str] = parameters.get("query_text", [])
    reference_time: str = parameters.get("reference_time", "")
    temporal_deviation: int = parameters.get("temporal_deviation", 0)

    logger.info(
        f"[TraceID:{trace_id}] 知识库 RAG 混合检索请求: "
        f"query_count={len(query_text_list)}, "
        f"reference_time='{reference_time}', "
        f"temporal_deviation={temporal_deviation}"
    )

    # 校验输入
    if not query_text_list:
        return "【检索错误】query_text 数组不能为空。"

    # 过滤空字符串
    valid_queries = [q.strip() for q in query_text_list if q.strip()]
    if not valid_queries:
        return "【检索错误】query_text 数组中所有查询词均为空。"

    # 从运行时上下文中获取 rag_orchestrator
    state_context = state_context or {}
    rag_orchestrator = state_context.get("rag_orchestrator")
    if not rag_orchestrator:
        logger.error(
            f"[TraceID:{trace_id}] 知识库 RAG 检索失败: "
            "rag_orchestrator 未注入到 state_context 中"
        )
        return "【系统错误】RAG 检索引擎未初始化，无法执行知识库检索。"

    try:
        # 构造混合检索参数：
        # - search_queries：向量检索使用的泛化 Query 列表
        # - query_text：第一个查询词作为基础查询文本
        # - reference_time：BM25 时间约束
        # - temporal_deviation：BM25 时间过滤偏差天数
        base_query = valid_queries[0]
        search_queries = valid_queries if len(valid_queries) > 1 else None
        ref_time = reference_time if reference_time.strip() else None

        knowledge_text = await rag_orchestrator.retrieve_and_format_knowledge(
            query_text=base_query,
            query_vector=[],
            search_queries=search_queries,
            reference_time=ref_time,
            temporal_deviation=temporal_deviation,
        )

        logger.info(
            f"[TraceID:{trace_id}] 知识库 RAG 混合检索成功: "
            f"query_count={len(valid_queries)}, "
            f"result_length={len(knowledge_text)}"
        )

        if not knowledge_text or not knowledge_text.strip():
            return "【检索结果】未在知识库中找到与查询相关的信息。"

        return knowledge_text

    except Exception as e:
        logger.error(
            f"[TraceID:{trace_id}] 知识库 RAG 混合检索异常: "
            f"query_count={len(valid_queries)}, error={e}"
        )
        return f"【检索错误】知识库检索过程中发生异常: {e!s}"
