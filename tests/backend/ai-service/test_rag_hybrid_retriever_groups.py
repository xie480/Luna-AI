import pytest
from unittest.mock import AsyncMock, MagicMock
from app.rag.hybrid_retriever import HybridRetriever
from app.repository.models import LongTermMemory, MemoryStatus

@pytest.mark.asyncio
async def test_hybrid_retriever_search_groups():
    # Mock PG Repo
    mock_pg_repo = AsyncMock()
    # Mock Qdrant Repo
    mock_qdrant_repo = AsyncMock()
    # Mock Inference Service
    mock_inference_svc = AsyncMock()

    # Setup returned values
    mock_inference_svc.get_embedding_vector.return_value = [0.1, 0.2, 0.3]
    # Qdrant search_groups_by_vector should return a list of memory_ids (strings)
    mock_qdrant_repo.search_groups_by_vector.return_value = ["mem_1", "mem_2"]
    
    # PG get_by_ids should return LongTermMemory objects
    mem_1 = LongTermMemory(id="mem_1", session_id="20230101", summary="summary 1", status=MemoryStatus.ACTIVE.value)
    mem_2 = LongTermMemory(id="mem_2", session_id="20230102", summary="summary 2", status=MemoryStatus.ACTIVE.value)
    mock_pg_repo.get_by_ids.return_value = [mem_1, mem_2]

    # Setup retriever
    retriever = HybridRetriever(
        ltm_pg_repo=mock_pg_repo,
        ltm_qdrant_repo=mock_qdrant_repo,
        inference_svc=mock_inference_svc,
        retrieval_top_k=5,
        rerank_top_k=2
    )

    # Disable FTS for this test by returning false in is_available check inside PGTextSearch
    # but the easiest way is to pass an empty reference_time and not FTS queries
    results = await retriever._vector_retrieve(
        query_text="测试",
        query_vector=[],
        search_queries=["测试查询1", "测试查询2"]
    )
    
    # Verify qdrant repo was called correctly
    assert mock_qdrant_repo.search_groups_by_vector.call_count == 2
    
    # Verify pg repo was called with deduplicated ids
    # The ids are deduplicated across the two queries
    mock_pg_repo.get_by_ids.assert_called_once()
    args, kwargs = mock_pg_repo.get_by_ids.call_args
    assert set(args[0]) == {"mem_1", "mem_2"}
    
    assert len(results) == 2
    assert results[0].id == "mem_1"
    assert results[1].id == "mem_2"
