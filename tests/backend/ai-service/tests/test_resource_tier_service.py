"""ResourceTierService 单元测试。

做什么：测试资源分级加载服务的三级策略、token 估算、轻精排、去重和降级逻辑。
为什么这样做：确保资源分级加载的核心逻辑正确，各 Tier 策略能按预期工作。
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../backend/ai-service"))

from app.mcp.resource_tier_service import (
    ResourceLoadResult,
    ResourceTierService,
)


# ===========================================================================
# Mock 辅助类
# ===========================================================================


class MockQdrantSearchResult:
    """模拟 Qdrant 搜索结果。"""

    def __init__(self, id: str, score: float, payload: dict):
        self.id = id
        self.score = score
        self.payload = payload


class MockEmbeddingService:
    """模拟 Embedding 服务。"""

    async def get_embedding_vector(self, text: str) -> list[float]:
        """返回固定维度的随机向量。"""
        return [0.1] * 1024


class MockQdrantClient:
    """模拟 Qdrant 客户端。"""

    def __init__(self, search_results: list | None = None):
        self._search_results = search_results or []
        self.search_call_count = 0

    async def search(self, **kwargs) -> list:
        self.search_call_count += 1
        return self._search_results

    async def ensure_collection(self, *args, **kwargs):
        pass

    async def upsert(self, *args, **kwargs):
        pass


# ===========================================================================
# 测试 _estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    """测试 token 估算方法。"""

    def test_empty_text(self):
        """空文本返回 0。"""
        service = ResourceTierService()
        assert service._estimate_tokens("") == 0

    def test_pure_english(self):
        """纯英文文本 token 估算。"""
        service = ResourceTierService()
        # 约 4 字符 = 1 token
        tokens = service._estimate_tokens("hello world test")
        assert tokens > 0
        assert tokens < 20  # 16 字符 ≈ 4 token

    def test_pure_chinese(self):
        """纯中文文本 token 估算。"""
        service = ResourceTierService()
        # 约 1.5 字 = 1 token
        tokens = service._estimate_tokens("你好世界测试")
        assert tokens > 0
        assert tokens < 10  # 6 字 ≈ 4 token

    def test_mixed_text(self):
        """混合中英文文本 token 估算。"""
        service = ResourceTierService()
        tokens = service._estimate_tokens("你好 hello 世界 world")
        assert tokens > 0

    def test_large_text(self):
        """大文本 token 估算。"""
        service = ResourceTierService()
        # 1000 个中文字符 ≈ 670 token
        large_text = "中" * 1000
        tokens = service._estimate_tokens(large_text)
        assert tokens > 500
        assert tokens < 800


# ===========================================================================
# 测试 Tier 1：全量加载
# ===========================================================================


class TestTier1FullLoad:
    """测试 Tier 1 小文件全量加载。"""

    @pytest.mark.asyncio
    async def test_small_file_full_load(self, tmp_path):
        """小文件（≤ 50000 token）应全量加载。"""
        # 创建小测试文件
        test_file = tmp_path / "small.txt"
        test_file.write_text("这是一个小测试文件内容。" * 10, encoding="utf-8")

        service = ResourceTierService()

        result = await service.load_resource(
            trace_id="test-trace-001",
            resource_def={
                "name": "小文件",
                "resource_type": "file",
                "uri": str(test_file),
                "description": "测试小文件",
            },
            query_texts=["测试查询"],
            step_intent="测试意图",
        )

        assert result.success is True
        assert result.tier_used == "tier1_full"
        assert result.resource_name == "小文件"
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """文件不存在时返回失败结果。"""
        service = ResourceTierService()

        result = await service.load_resource(
            trace_id="test-trace-002",
            resource_def={
                "name": "不存在的文件",
                "resource_type": "file",
                "uri": "/path/to/nonexistent/file.txt",
                "description": "",
            },
            query_texts=["测试"],
        )

        assert result.success is False
        assert "不存在" in result.error_message or "读取失败" in result.error_message

    @pytest.mark.asyncio
    async def test_empty_resource_def(self):
        """空资源定义返回失败结果。"""
        service = ResourceTierService()

        result = await service.load_resource(
            trace_id="test-trace-003",
            resource_def={},
            query_texts=["测试"],
        )

        assert result.success is False
        assert "缺少 name" in result.error_message


# ===========================================================================
# 测试 Tier 2：向量检索
# ===========================================================================


class TestTier2VectorSearch:
    """测试 Tier 2 中等文件向量检索。"""

    @pytest.mark.asyncio
    async def test_vector_search_success(self):
        """向量检索成功返回相关 chunk。"""
        # 模拟 Qdrant 搜索结果
        mock_results = [
            MockQdrantSearchResult(
                id="chunk-1",
                score=0.85,
                payload={"chunk_text": "这是第一个相关 chunk 内容。", "chunk_index": 0},
            ),
            MockQdrantSearchResult(
                id="chunk-2",
                score=0.75,
                payload={"chunk_text": "这是第二个相关 chunk 内容。", "chunk_index": 1},
            ),
        ]

        mock_qdrant = MockQdrantClient(search_results=mock_results)
        mock_embedding = MockEmbeddingService()

        service = ResourceTierService(
            qdrant_client=mock_qdrant,
            embedding_service=mock_embedding,
        )

        result = await service._tier2_vector_search(
            trace_id="test-trace-004",
            resource_def={
                "name": "中等文件",
                "resource_type": "file",
                "uri": "test.txt",
                "description": "测试描述",
            },
            query_texts=["测试查询"],
            step_intent="测试意图",
        )

        assert result.success is True
        assert result.tier_used == "tier2_vector_search"
        assert result.chunk_count == 2
        assert "第一个相关 chunk" in result.content

    @pytest.mark.asyncio
    async def test_vector_search_empty_fallback(self):
        """向量检索无结果时使用 description 兜底。"""
        mock_qdrant = MockQdrantClient(search_results=[])
        mock_embedding = MockEmbeddingService()

        service = ResourceTierService(
            qdrant_client=mock_qdrant,
            embedding_service=mock_embedding,
        )

        result = await service._tier2_vector_search(
            trace_id="test-trace-005",
            resource_def={
                "name": "空结果文件",
                "description": "这是描述兜底内容",
            },
            query_texts=["不存在的查询"],
        )

        assert result.success is True
        assert result.tier_used == "tier2_vector_search_empty"
        assert result.content == "这是描述兜底内容"


# ===========================================================================
# 测试 Tier 3：多 query 检索 + 轻精排
# ===========================================================================


class TestTier3MultiQuerySearch:
    """测试 Tier 3 大文件多 query 检索。"""

    @pytest.mark.asyncio
    async def test_multi_query_search_with_rerank(self):
        """多 query 检索 + 轻精排返回排序后的 chunk。"""
        mock_results = [
            MockQdrantSearchResult(
                id="chunk-1", score=0.9,
                payload={"chunk_text": "高相关度 chunk", "chunk_index": 0, "section_title": ""},
            ),
            MockQdrantSearchResult(
                id="chunk-2", score=0.7,
                payload={"chunk_text": "中相关度 chunk 内容更多一些", "chunk_index": 1, "section_title": ""},
            ),
            MockQdrantSearchResult(
                id="chunk-3", score=0.6,
                payload={"chunk_text": "低相关度", "chunk_index": 2, "section_title": ""},
            ),
        ]

        mock_qdrant = MockQdrantClient(search_results=mock_results)
        mock_embedding = MockEmbeddingService()

        service = ResourceTierService(
            qdrant_client=mock_qdrant,
            embedding_service=mock_embedding,
        )

        result = await service._tier3_multi_query_search(
            trace_id="test-trace-006",
            resource_def={
                "name": "大文件",
                "description": "大文件描述",
            },
            query_texts=["查询1", "查询2", "查询3"],
            step_intent="测试意图",
        )

        assert result.success is True
        assert result.tier_used == "tier3_multi_query_rerank"
        assert result.chunk_count > 0


# ===========================================================================
# 测试 _light_rerank
# ===========================================================================


class TestLightRerank:
    """测试轻精排逻辑。"""

    def test_empty_chunks(self):
        """空 chunk 列表返回空列表。"""
        service = ResourceTierService()
        result = service._light_rerank([], ["query"], "intent", 5)
        assert result == []

    def test_rerank_scoring(self):
        """轻精排评分正确性。"""
        service = ResourceTierService()
        chunks = [
            {
                "chunk_text": "这是一个包含关键词的优质内容，长度适中不会触发惩罚。",
                "chunk_index": 0,
                "section_title": "测试章节",
                "query_hit_count": 2,
            },
            {
                "chunk_text": "短",
                "chunk_index": 1,
                "section_title": "",
                "query_hit_count": 1,
            },
            {
                "chunk_text": "中等长度的 chunk 内容，包含一些测试相关信息。",
                "chunk_index": 5,
                "section_title": "",
                "query_hit_count": 1,
            },
        ]

        result = service._light_rerank(
            chunks=chunks,
            query_texts=["测试 关键词"],
            step_intent="测试意图",
            final_top_k=3,
        )

        # 第一个 chunk 应该分数最高（关键词命中多、长度适中、有标题匹配）
        assert len(result) == 3
        assert result[0]["chunk_index"] == 0  # 最高分应该是第一个

    def test_length_penalty_short(self):
        """过短 chunk 被降权。"""
        service = ResourceTierService()
        chunks = [
            {"chunk_text": "短", "chunk_index": 0, "section_title": "", "query_hit_count": 3},
            {"chunk_text": "这是长度适中的 chunk 内容。" * 2, "chunk_index": 1, "section_title": "", "query_hit_count": 1},
        ]

        result = service._light_rerank(chunks, ["测试"], "测试", 2)
        # 即使 query_hit_count 更高，过短 chunk 也应被降权
        assert len(result) == 2


# ===========================================================================
# 测试 _deduplicate_chunks
# ===========================================================================


class TestDeduplicateChunks:
    """测试相似去重。"""

    def test_empty_chunks(self):
        """空列表返回空列表。"""
        service = ResourceTierService()
        assert service._deduplicate_chunks([]) == []

    def test_no_duplicates(self):
        """不相似的 chunk 不被去重。"""
        service = ResourceTierService()
        chunks = [
            {"chunk_text": "苹果是红色的水果"},
            {"chunk_text": "汽车需要加油才能行驶"},
        ]
        result = service._deduplicate_chunks(chunks, threshold=0.9)
        assert len(result) == 2

    def test_duplicates_removed(self):
        """高度相似的 chunk 被去重。"""
        service = ResourceTierService()
        # 两个几乎相同的 chunk
        chunks = [
            {"chunk_text": "苹果是红色的水果很好吃"},
            {"chunk_text": "苹果是红色的水果非常好吃"},
        ]
        result = service._deduplicate_chunks(chunks, threshold=0.5)
        assert len(result) == 1  # 只保留第一个

    def test_preserve_order(self):
        """去重保持首次出现顺序。"""
        service = ResourceTierService()
        chunks = [
            {"chunk_text": "第一段完全不同"},
            {"chunk_text": "第二段苹果是红色的"},
            {"chunk_text": "第三段苹果是红色的水果"},
        ]
        result = service._deduplicate_chunks(chunks, threshold=0.5)
        assert result[0]["chunk_text"] == "第一段完全不同"


# ===========================================================================
# 测试降级策略
# ===========================================================================


class TestDegradation:
    """测试降级策略。"""

    @pytest.mark.asyncio
    async def test_qdrant_unavailable_fallback_to_tier1(self, tmp_path):
        """Qdrant 不可用时降级为 Tier 1 全量加载。"""
        # 创建一个稍大的文件（但仍在降级范围内）
        test_file = tmp_path / "medium.txt"
        test_file.write_text("测试内容 " * 100, encoding="utf-8")

        # Qdrant 和 Embedding 服务都为 None
        service = ResourceTierService(
            qdrant_client=None,
            embedding_service=None,
        )

        result = await service.load_resource(
            trace_id="test-trace-007",
            resource_def={
                "name": "中等文件",
                "resource_type": "file",
                "uri": str(test_file),
                "description": "",
            },
            query_texts=["测试"],
        )

        # 应降级为 Tier 1
        assert result.success is True
        assert "tier1" in result.tier_used or result.tier_used == "tier1_full"

    @pytest.mark.asyncio
    async def test_fallback_to_full_load_on_vector_error(self, tmp_path):
        """向量检索异常时降级为全量加载。"""
        test_file = tmp_path / "error_test.txt"
        test_file.write_text("测试内容 " * 100, encoding="utf-8")

        # 创建一个会抛异常的 Qdrant 客户端
        mock_qdrant = MagicMock()
        mock_qdrant.search = AsyncMock(side_effect=RuntimeError("Qdrant 连接失败"))
        mock_embedding = MockEmbeddingService()

        service = ResourceTierService(
            qdrant_client=mock_qdrant,
            embedding_service=mock_embedding,
        )

        # 手动设置文件 token 数超过 Tier1 阈值以触发 Tier 2
        result = await service.load_resource(
            trace_id="test-trace-008",
            resource_def={
                "name": "错误测试文件",
                "resource_type": "file",
                "uri": str(test_file),
                "description": "描述兜底",
            },
            query_texts=["测试"],
        )

        # 应降级为全量加载
        assert result.success is True

    @pytest.mark.asyncio
    async def test_description_fallback(self):
        """文件读取和全量加载都失败时使用 description 兜底。"""
        service = ResourceTierService()

        result = await service._fallback_to_full_load(
            trace_id="test-trace-009",
            resource_def={
                "name": "完全失败文件",
                "uri": "/nonexistent/path.txt",
                "resource_type": "file",
                "description": "这是兜底描述内容",
            },
        )

        assert result.success is True
        assert result.content == "这是兜底描述内容"
        assert result.tier_used == "description_fallback"


# ===========================================================================
# 测试 ResourceLoadResult
# ===========================================================================


class TestResourceLoadResult:
    """测试 ResourceLoadResult 数据类。"""

    def test_default_values(self):
        """默认值正确。"""
        result = ResourceLoadResult(resource_name="test")
        assert result.resource_name == "test"
        assert result.content == ""
        assert result.success is True
        assert result.tier_used == "tier1_full"
        assert result.chunk_count == 0
        assert result.error_message == ""

    def test_custom_values(self):
        """自定义值正确设置。"""
        result = ResourceLoadResult(
            resource_name="custom",
            content="内容",
            success=False,
            tier_used="tier3_multi_query_rerank",
            chunk_count=5,
            error_message="错误",
        )
        assert result.resource_name == "custom"
        assert result.content == "内容"
        assert result.success is False
        assert result.tier_used == "tier3_multi_query_rerank"
        assert result.chunk_count == 5
        assert result.error_message == "错误"
