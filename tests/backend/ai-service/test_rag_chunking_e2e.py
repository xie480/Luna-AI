import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

# 配置日志
logging.basicConfig(level=logging.INFO)

from app.memory.manager import Manager
from app.repository.models import LongTermMemory, MemoryStatus
from app.rag.chunker import parse_long_summary_to_chunks
import app.api.internal_service

async def main():
    print("=== 开始测试 RAG 切片与分组检索全流程 ===")

    # 1. 模拟外部依赖
    mock_redis = AsyncMock()
    mock_redis.get_context.return_value = (
        MagicMock(core_summary="核心摘要", key_facts=""),
        [MagicMock(userContent="你好", assistantContent="你好，我是Luna", thought="", emotion="")]
    )

    mock_pg = AsyncMock()
    # 拦截 PG 的保存操作
    saved_memories = {}
    async def mock_pg_save(mem):
        saved_memories[mem.id] = mem
    mock_pg.save.side_effect = mock_pg_save

    async def mock_pg_get_by_ids(ids):
        return [saved_memories[id] for id in ids if id in saved_memories]
    mock_pg.get_by_ids.side_effect = mock_pg_get_by_ids

    # 模拟 HybridRetriever 内部使用的 FTS retriever
    mock_pg.is_available = True
    # mock_pg 其实不直接实现 search_by_text，是由 PGTextSearch 封装，在真实环境里 PGTextSearch 会检查 repo
    # 此处我们让它为空返回，走向量主流程即可

    mock_qdrant = AsyncMock()
    saved_qdrant_points = []
    async def mock_qdrant_save_chunks(memory_id, session_id, chunks, vectors, status):
        print(f"\n[Qdrant 拦截] 收到存储请求: memory_id={memory_id}, 切片数量={len(chunks)}")
        for c, v in zip(chunks, vectors):
            print(f"  -> 切片类型: {c.chunk_type}, 内容: {c.content}")
            saved_qdrant_points.append({
                "memory_id": memory_id,
                "chunk": c,
                "vector": v
            })
    mock_qdrant.save_chunks_with_vectors.side_effect = mock_qdrant_save_chunks

    async def mock_qdrant_search_groups(vector, top_k):
        # 简单模拟：返回所有的独立的 memory_id
        ids = list(set(p["memory_id"] for p in saved_qdrant_points))
        print(f"\n[Qdrant 拦截] 模拟 Qdrant 原生 search_groups，返回去重后的 memory_ids: {ids}")
        return ids
    mock_qdrant.search_groups_by_vector.side_effect = mock_qdrant_search_groups

    mock_inference = AsyncMock()
    # 模拟 Embedding：返回固定的假向量
    mock_inference.get_embedding_vector.return_value = [0.1] * 768
    # 模拟 Rerank：保持原序
    async def mock_rerank(query, docs):
        return [{"index": i, "score": 0.9} for i in range(len(docs))]
    mock_inference.rerank_documents.side_effect = mock_rerank

    mock_prompt_mgr = AsyncMock()
    mock_prompt_mgr.assemble_prompt.return_value = "Mocked Prompt"

    # Patch internal_service
    internal_service_mock = AsyncMock()
    long_summary_text = (
        "梗概：这是一段测试的会话核心梗概内容，用户和Luna进行了友好的交流。\n"
        "关键事实：1.用户今天心情很好;2.用户明天要早起;3.Luna答应叫用户起床;"
    )
    internal_service_mock.long_summarize.return_value = long_summary_text
    app.api.internal_service.internal_service = internal_service_mock

    # 2. 组装 Manager
    manager = Manager(
        redis_repo=mock_redis,
        ltm_pg_repo=mock_pg,
        ltm_qdrant_repo=mock_qdrant,
        prompt_mgr=mock_prompt_mgr,
        qdrant_client=AsyncMock(),
        inference_svc=mock_inference,
        retrieval_top_k=5,
        rerank_top_k=3
    )
    
    # 禁用 FTS，以确保纯粹测试向量路由 (is_available 是 property, 我们可以 mock _repo)
    manager.retriever.fts_retriever._repo = None

    # 3. 模拟会话流转，触发 _compress_and_commit
    print("\n=== 第一阶段：触发会话压缩与切片存储 ===")
    await manager.rollover_session("20231010")

    # 4. 模拟检索流程
    print("\n=== 第二阶段：触发混合检索 (RAG) ===")
    formatted_result = await manager.retrieve_and_format_memories(
        query_text="测试查询",
        query_vector=[0.1] * 768,
        search_queries=["明天早起"]
    )

    print("\n=== 最终提供给 LLM 的格式化记忆文本 ===")
    print(formatted_result)
    print("=========================================")

if __name__ == "__main__":
    asyncio.run(main())