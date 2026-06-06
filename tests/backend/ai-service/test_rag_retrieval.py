from dataclasses import dataclass
from typing import Any

import pytest

from app.rag.retrieval import RagRetrievalOrchestrator
from app.rag.types import RagSearchRequest
from app.types.constants import RagRetrievalRoute


@dataclass
class FakeChunk:
    chunk_id: str
    doc_id: str
    parent_id: str | None
    content_text: str
    meta_payload: dict[str, Any]


@dataclass
class FakeDocument:
    id: str
    filename: str
    source_type: str


@dataclass
class FakeCandidate:
    chunk: FakeChunk
    document: FakeDocument
    score: float


class FakePGRepo:
    """用于验证检索编排行为的内存 PG 仓库。"""

    def __init__(self) -> None:
        self.document = FakeDocument(id="2001", filename="phase7.md", source_type="local_file")
        self.parent = FakeChunk(
            chunk_id="3001",
            doc_id="2001",
            parent_id=None,
            content_text="父块包含完整的数据库初始化步骤与上下文。",
            meta_payload={"chunk_role": "parent"},
        )
        self.child = FakeChunk(
            chunk_id="3002",
            doc_id="2001",
            parent_id="3001",
            content_text="数据库初始化步骤。",
            meta_payload={"chunk_role": "child"},
        )

    async def search_by_text(self, query_text: str, top_k: int):
        return [FakeCandidate(chunk=self.child, document=self.document, score=0.8)]

    async def get_chunks_by_ids(self, chunk_ids: list[str]):
        if "3002" in chunk_ids:
            return [FakeCandidate(chunk=self.child, document=self.document, score=0.0)]
        return []

    async def get_parent_chunks(self, parent_ids: list[str]):
        if "3001" in parent_ids:
            return {"3001": self.parent}
        return {}


class FakeQdrantRepo:
    """用于验证向量召回融合的内存 Qdrant 仓库。"""

    async def search(self, query_vector: list[float], top_k: int):
        from app.repository.rag_qdrant import RagVectorHit

        return [RagVectorHit(chunk_id="3002", document_id="2001", score=0.91)]


class FakeInferenceService:
    """用于验证 Embedding 与 Rerank 调用的确定性推理服务。"""

    async def get_embedding_vector(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def rerank_documents(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        return [{"index": index, "score": 0.95 - index * 0.01} for index, _ in enumerate(documents)]


class SilentPublisher:
    """测试用事件发布器，避免触发真实 SSE 通道。"""

    def __init__(self) -> None:
        self.thoughts: list[tuple[str, str]] = []
        self.citations: list[dict[str, Any]] = []

    async def publish_thought(self, trace_id: str, stage: str, msg: str) -> None:
        self.thoughts.append((stage, msg))

    async def publish_citations(self, trace_id: str, citations: list[dict[str, Any]]) -> None:
        self.citations.extend(citations)


@pytest.mark.asyncio
async def test_hybrid_search_returns_parent_expanded_evidence():
    """验证混合检索命中 child 后会扩展 parent 正文并生成引用。"""
    publisher = SilentPublisher()
    orchestrator = RagRetrievalOrchestrator(
        pg_repo=FakePGRepo(),
        qdrant_repo=FakeQdrantRepo(),
        inference_svc=FakeInferenceService(),
        event_publisher=publisher,
    )

    response = await orchestrator.search(
        RagSearchRequest(query="如何初始化数据库", route=RagRetrievalRoute.HYBRID),
        trace_id="9001",
    )

    assert response.route == RagRetrievalRoute.HYBRID
    assert response.evidences
    assert response.evidences[0].content == "父块包含完整的数据库初始化步骤与上下文。"
    assert response.citations[0]["chunk"] == "3002"
    assert publisher.thoughts
    assert publisher.citations


@pytest.mark.asyncio
async def test_keyword_route_skips_vector_dependency():
    """验证 Keyword 路由可在无 Qdrant 与无推理服务时工作。"""
    orchestrator = RagRetrievalOrchestrator(
        pg_repo=FakePGRepo(),
        qdrant_repo=None,
        inference_svc=None,
        event_publisher=SilentPublisher(),
    )

    response = await orchestrator.search(
        RagSearchRequest(query="数据库 报错", route=RagRetrievalRoute.KEYWORD),
        trace_id="9002",
    )

    assert response.route == RagRetrievalRoute.KEYWORD
    assert len(response.evidences) == 1
    assert "引用 1" in response.prompt_context
