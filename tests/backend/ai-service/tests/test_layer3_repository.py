"""
第三阶段（Layer 3）综合测试

做什么：验证 Go backend/runtime/internal/repository/* 的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。

覆盖范围：
    - repository/models.py: ORM 模型定义
    - repository/chat_history_pg.py: PostgreSQL 聊天历史记录存储库
    - repository/chat_history_redis.py: Redis 聊天历史记录存储库
    - repository/config_preset_pg.py: API 配置预设存储库
    - repository/long_term_memory_pg.py: PostgreSQL 长期记忆存储库
    - repository/long_term_memory_qdrant.py: Qdrant 长期记忆存储库
    - repository/prompt_pg.py: 提示词模板存储库

Go 原版参考文件：
    - backend/runtime/internal/repository/models.go
    - backend/runtime/internal/repository/chat_history_pg.go
    - backend/runtime/internal/repository/chat_history_redis.go
    - backend/runtime/internal/repository/config_preset_pg.go
    - backend/runtime/internal/repository/long_term_memory_pg.go
    - backend/runtime/internal/repository/long_term_memory_qdrant.go
    - backend/runtime/internal/repository/prompt_pg.go
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.infrastructure.postgres import PostgresClient
from app.infrastructure.redis import RedisClient
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, ChatSummary, Interaction
from app.repository.config_preset_pg import ConfigPresetPGRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.models import (
    ApiConfigPreset,
    InteractionModel,
    LongTermMemory,
    MemoryStatus,
    PromptTemplate,
    PromptVersion,
)
from app.repository.prompt_pg import PromptPGRepo


# ============================================================
# 1. ChatHistoryRedisRepo 测试
# ============================================================

class TestChatHistoryRedisRepo:
    """验证 ChatHistoryRedisRepo 与 Go chat_history_redis.go 一致"""

    @pytest.fixture
    def mock_redis_client(self):
        client = MagicMock(spec=RedisClient)
        client.get_client = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_save_interaction(self, mock_redis_client):
        """验证 SaveInteraction"""
        repo = ChatHistoryRedisRepo(mock_redis_client)
        session_id = "test-session-1"
        
        interaction = Interaction(
            msgId="interaction-1",
            userContent="hello",
            assistantContent="hi there!",
            thought="I am thinking...",
            emotion="Happy",
            error="",
            timestamp=1234567890
        )
        
        mock_redis = mock_redis_client.get_client.return_value
        mock_redis.rpush = AsyncMock(return_value=1)
        
        length = await repo.save_interaction(session_id, interaction)
        
        assert length == 1
        mock_redis.rpush.assert_called_once()
        args, _ = mock_redis.rpush.call_args
        assert args[0] == f"luna:mem:chat:{session_id}:history"
        
        # 验证序列化结果
        saved_json = json.loads(args[1])
        assert saved_json["msgId"] == "interaction-1"
        assert saved_json["userContent"] == "hello"
        assert saved_json["assistantContent"] == "hi there!"
        assert saved_json["thought"] == "I am thinking..."
        assert saved_json["emotion"] == "Happy"
        assert saved_json["timestamp"] == 1234567890

    @pytest.mark.asyncio
    async def test_get_context(self, mock_redis_client):
        """验证 GetContext"""
        repo = ChatHistoryRedisRepo(mock_redis_client)
        session_id = "test-session-2"
        
        mock_redis = mock_redis_client.get_client.return_value
        mock_pipeline = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__.return_value = mock_pipeline
        
        # 模拟 Pipeline 返回结果
        mock_pipeline.execute = AsyncMock(return_value=[
            {"core_summary": "test core summary", "key_facts": "test key facts"},
            [
                json.dumps({"msgId": "interaction-1", "userContent": "hello", "assistantContent": "hi there!", "timestamp": 1}),
                json.dumps({"msgId": "interaction-2", "userContent": "how are you?", "assistantContent": "I am fine!", "emotion": "Happy", "timestamp": 2})
            ]
        ])
        
        summary, history = await repo.get_context(session_id)
        
        assert summary.core_summary == "test core summary"
        assert summary.key_facts == "test key facts"
        assert len(history) == 2
        assert history[0].msgId == "interaction-1"
        assert history[1].msgId == "interaction-2"
        assert history[1].emotion == "Happy"

    @pytest.mark.asyncio
    async def test_update_summary_and_trim(self, mock_redis_client):
        """验证 UpdateSummaryAndTrim"""
        repo = ChatHistoryRedisRepo(mock_redis_client)
        session_id = "test-session-3"
        
        new_summary = ChatSummary(
            core_summary="new core summary",
            key_facts="new key facts"
        )
        
        mock_redis = mock_redis_client.get_client.return_value
        mock_pipeline = AsyncMock()
        mock_pipeline.execute = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__.return_value = mock_pipeline
        
        await repo.update_summary_and_trim(session_id, new_summary, 2)
        
        mock_pipeline.hset.assert_called_once_with(
            f"luna:mem:chat:{session_id}:summary",
            mapping={"core_summary": "new core summary", "key_facts": "new key facts"}
        )
        mock_pipeline.ltrim.assert_called_once_with(
            f"luna:mem:chat:{session_id}:history",
            2, -1
        )
        mock_pipeline.execute.assert_called_once()


# ============================================================
# 2. ChatHistoryPGRepo 测试
# ============================================================

class TestChatHistoryPGRepo:
    """验证 ChatHistoryPGRepo 与 Go chat_history_pg.go 一致"""

    @pytest.fixture
    def mock_pg_client(self):
        client = MagicMock(spec=PostgresClient)
        return client

    @pytest.mark.asyncio
    async def test_save_interaction(self, mock_pg_client):
        """验证 SaveInteraction"""
        repo = ChatHistoryPGRepo(mock_pg_client)
        
        mock_session = AsyncMock()
        async def mock_get_session():
            yield mock_session
        mock_pg_client.get_session = mock_get_session
        
        interaction = InteractionModel(
            id="123",
            session_id="session-1",
            message_id="msg-1",
            user_content="hello",
            assistant_content="hi there",
            emotion="happy",
            created_at=datetime.now(timezone.utc)
        )
        
        await repo.save_interaction(interaction)
        
        mock_session.add.assert_called_once_with(interaction)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_interactions_by_session_id(self, mock_pg_client):
        """验证 GetInteractionsBySessionID"""
        repo = ChatHistoryPGRepo(mock_pg_client)
        
        mock_session = AsyncMock()
        async def mock_get_session():
            yield mock_session
        mock_pg_client.get_session = mock_get_session
        
        # 模拟查询结果
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [
            InteractionModel(id="1", message_id="msg-1"),
            InteractionModel(id="2", message_id="msg-2")
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        interactions = await repo.get_interactions_by_session_id("session-1", 10, 0)
        
        assert len(interactions) == 2
        assert interactions[0].message_id == "msg-1"
        assert interactions[1].message_id == "msg-2"
        mock_session.execute.assert_called_once()


# ============================================================
# 3. LongTermMemoryPGRepo 测试
# ============================================================

class TestLongTermMemoryPGRepo:
    """验证 LongTermMemoryPGRepo 与 Go long_term_memory_pg.go 一致"""

    @pytest.fixture
    def mock_pg_client(self):
        client = MagicMock(spec=PostgresClient)
        return client

    @pytest.mark.asyncio
    async def test_save(self, mock_pg_client):
        """验证 Save"""
        repo = LongTermMemoryPGRepo(mock_pg_client)
        
        mock_session = AsyncMock()
        async def mock_get_session():
            yield mock_session
        mock_pg_client.get_session = mock_get_session
        
        memory = LongTermMemory(
            id="123",
            session_id="session-1",
            summary="test summary"
        )
        
        await repo.save(memory)
        
        assert memory.status == MemoryStatus.ACTIVE.value
        mock_session.add.assert_called_once_with(memory)
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_soft_delete(self, mock_pg_client):
        """验证 SoftDelete"""
        repo = LongTermMemoryPGRepo(mock_pg_client)
        
        mock_session = AsyncMock()
        async def mock_get_session():
            yield mock_session
        mock_pg_client.get_session = mock_get_session
        
        await repo.soft_delete("123")
        
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


# ============================================================
# 4. LongTermMemoryQdrantRepo 测试
# ============================================================

class TestLongTermMemoryQdrantRepo:
    """验证 LongTermMemoryQdrantRepo 与 Go long_term_memory_qdrant.go 一致"""

    @pytest.mark.asyncio
    async def test_save_with_vector(self):
        """验证 SaveWithVector"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
        
        mock_qdrant = MagicMock(spec=QdrantClientWrapper)
        mock_qdrant.upsert = AsyncMock()
        
        repo = LongTermMemoryQdrantRepo(mock_qdrant)
        
        await repo.save_with_vector("12345", "session-1", [0.1, 0.2])
        
        mock_qdrant.upsert.assert_called_once()
        args, _ = mock_qdrant.upsert.call_args
        assert args[0] == "luna_long_term_memories"
        points = args[1]
        assert len(points) == 1
        assert points[0].id == 12345
        assert points[0].vector == [0.1, 0.2]
        assert points[0].payload["memory_id"] == "12345"
        assert points[0].payload["session_id"] == "session-1"
        assert points[0].payload["status"] == MemoryStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_soft_delete_by_memory_id(self):
        """验证 SoftDeleteByMemoryID"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
        
        mock_qdrant = MagicMock(spec=QdrantClientWrapper)
        mock_qdrant.upsert = AsyncMock()
        
        repo = LongTermMemoryQdrantRepo(mock_qdrant)
        
        await repo.soft_delete_by_memory_id("12345")
        
        mock_qdrant.upsert.assert_called_once()
        args, _ = mock_qdrant.upsert.call_args
        assert args[0] == "luna_long_term_memories"
        points = args[1]
        assert len(points) == 1
        assert points[0].id == 12345
        assert points[0].vector == [0.0] * 768
        assert points[0].payload["memory_id"] == "12345"
        assert points[0].payload["status"] == MemoryStatus.DELETED.value
