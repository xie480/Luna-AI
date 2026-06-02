"""
Layer 7 综合测试

做什么：验证遗漏的支撑模块（InferenceService, Metrics, ModelRouter）的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.inference.service import InferenceService
from app.router.model_router import ModelRouter, ModelSize, NodeType
from app.telemetry.metrics import MetricPoint, RingBuffer


# ============================================================
# 1. InferenceService 测试
# ============================================================

class TestInferenceService:
    """验证 InferenceService 与 Go service.go 一致"""

    @pytest.mark.asyncio
    async def test_get_embedding_vector(self):
        mock_ai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.vector_json = "[0.1, 0.2, 0.3]"
        mock_ai_client.embedding = AsyncMock(return_value=mock_resp)
        
        svc = InferenceService(mock_ai_client)
        vector = await svc.get_embedding_vector("test text")
        
        assert vector == [0.1, 0.2, 0.3]
        mock_ai_client.embedding.assert_called_once()
        args, _ = mock_ai_client.embedding.call_args
        assert args[0].text == "test text"

    @pytest.mark.asyncio
    async def test_rerank_documents(self):
        mock_ai_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.scores = [0.5, 0.9, 0.2]
        mock_ai_client.rerank = AsyncMock(return_value=mock_resp)
        
        svc = InferenceService(mock_ai_client)
        results = await svc.rerank_documents("query", ["doc1", "doc2", "doc3"])
        
        assert len(results) == 3
        # 验证降序排序
        assert results[0]["index"] == 1
        assert results[0]["score"] == 0.9
        assert results[1]["index"] == 0
        assert results[1]["score"] == 0.5
        assert results[2]["index"] == 2
        assert results[2]["score"] == 0.2


# ============================================================
# 2. Metrics 测试
# ============================================================

class TestMetrics:
    """验证 Metrics 与 Go metrics.go 一致"""

    def test_ring_buffer(self):
        buffer = RingBuffer(3)
        
        # 测试空获取
        assert buffer.get_recent(5) == []
        
        # 测试添加
        p1 = MetricPoint(datetime.now(), 10.0, 100.0, 1, 10, 0.0)
        p2 = MetricPoint(datetime.now(), 20.0, 200.0, 2, 20, 0.0)
        p3 = MetricPoint(datetime.now(), 30.0, 300.0, 3, 30, 0.0)
        p4 = MetricPoint(datetime.now(), 40.0, 400.0, 4, 40, 0.0)
        
        buffer.push(p1)
        buffer.push(p2)
        
        recent = buffer.get_recent(2)
        assert len(recent) == 2
        assert recent[0]["system_cpu_usage"] == 10.0
        assert recent[1]["system_cpu_usage"] == 20.0
        
        # 测试覆盖
        buffer.push(p3)
        buffer.push(p4) # 覆盖 p1
        
        recent = buffer.get_recent(3)
        assert len(recent) == 3
        assert recent[0]["system_cpu_usage"] == 20.0
        assert recent[1]["system_cpu_usage"] == 30.0
        assert recent[2]["system_cpu_usage"] == 40.0


# ============================================================
# 3. ModelRouter 测试
# ============================================================

class TestModelRouter:
    """验证 ModelRouter 与 Go model_router.go 一致"""

    @pytest.mark.asyncio
    async def test_get_model_for_node(self):
        mock_repo = MagicMock()
        mock_preset = MagicMock()
        mock_preset.large_model_config = {"api_key": "large_key"}
        mock_preset.small_model_config = {"api_key": "small_key"}
        mock_repo.get_active = AsyncMock(return_value=mock_preset)
        
        router = ModelRouter(mock_repo)
        
        # 测试获取大模型
        config1 = await router.get_model_for_node(NodeType.CHAT)
        assert config1["api_key"] == "large_key"
        
        # 测试获取小模型
        config2 = await router.get_model_for_node(NodeType.SUMMARIZE)
        assert config2["api_key"] == "small_key"
        
        # 测试缓存命中
        mock_repo.get_active.reset_mock()
        config3 = await router.get_model_for_node(NodeType.CHAT)
        assert config3["api_key"] == "large_key"
        mock_repo.get_active.assert_not_called()
        
        # 测试清除缓存
        await router.clear_cache()
        config4 = await router.get_model_for_node(NodeType.CHAT)
        assert config4["api_key"] == "large_key"
        mock_repo.get_active.assert_called_once()
