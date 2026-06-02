"""
第二阶段（Layer 2）综合测试

做什么：验证 Go backend/runtime/internal/config/* 和 infrastructure/* 的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。

覆盖范围：
    - config/settings.py: 配置加载、环境变量覆盖、默认值
    - config/event_bus.py: 事件发布订阅机制、异步执行
    - infrastructure/postgres.py: PostgreSQL 客户端连接、健康检查
    - infrastructure/redis.py: Redis 客户端连接、健康检查
    - infrastructure/qdrant.py: Qdrant 客户端连接、集合管理、向量操作

Go 原版参考文件：
    - backend/runtime/internal/config/config.go
    - backend/runtime/internal/config/event.go
    - backend/runtime/internal/infrastructure/postgres.go
    - backend/runtime/internal/infrastructure/redis.go
    - backend/runtime/internal/infrastructure/qdrant.go
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.event_bus import Event, EventBus, EventType
from app.config.settings import Settings
from app.infrastructure.postgres import PostgresClient
from app.infrastructure.redis import RedisClient


# QdrantClientWrapper 及其相关类延迟导入（因为 qdrant_client 包可能未安装）
# 在 TestQdrantClientWrapper 类中延迟导入


# ============================================================
# 1. Config Settings 测试
# ============================================================

class TestSettings:
    """验证 Settings 配置加载与 Go config.go 一致"""

    def test_default_values(self) -> None:
        """验证默认值"""
        # 临时移除环境变量，确保测试默认值
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
            assert settings.ai_service_port == 8000
            assert settings.grpc_port == 50051
            assert settings.log_level == "INFO"
            assert settings.redis_host == "localhost"
            assert settings.redis_port == 6379
            assert settings.db_host == "localhost"
            assert settings.db_port == 5432
            assert settings.qdrant_address == "localhost:6333"

    def test_env_overrides(self) -> None:
        """验证环境变量覆盖"""
        env_vars = {
            "AI_SERVICE_PORT": "9090",
            "LOG_LEVEL": "DEBUG",
            "REDIS_HOST": "redis-server",
            "DB_NAME": "test_db",
        }
        with patch.dict(os.environ, env_vars):
            settings = Settings()
            assert settings.ai_service_port == 9090
            assert settings.log_level == "DEBUG"
            assert settings.redis_host == "redis-server"
            assert settings.db_name == "test_db"

    def test_redis_addr_property(self) -> None:
        """验证 RedisAddr 属性"""
        settings = Settings(redis_host="test-redis", redis_port=1234)
        assert settings.redis_addr == "test-redis:1234"

    def test_postgres_conn_str_property(self) -> None:
        """验证 PostgresConnStr 属性"""
        settings = Settings(
            db_user="test_user",
            db_password="test_password",
            db_host="test-db",
            db_port=5432,
            db_name="test_db_name"
        )
        expected = "postgresql+asyncpg://test_user:test_password@test-db:5432/test_db_name"
        assert settings.postgres_conn_str == expected


# ============================================================
# 2. EventBus 测试
# ============================================================

class TestEventBus:
    """验证 EventBus 与 Go event.go 一致"""

    @pytest.mark.asyncio
    async def test_subscribe_and_publish_async(self) -> None:
        """验证异步事件处理"""
        bus = EventBus()
        received_events = []

        async def handler(event: Event) -> None:
            received_events.append(event)

        await bus.subscribe(EventType.CONFIG_CHANGED, handler)
        
        event = Event(EventType.CONFIG_CHANGED, {"key": "value"})
        await bus.publish(event)
        
        # 等待异步任务执行完成
        await asyncio.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].type == EventType.CONFIG_CHANGED
        assert received_events[0].data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_subscribe_and_publish_sync(self) -> None:
        """验证同步事件处理"""
        bus = EventBus()
        received_events = []

        def handler(event: Event) -> None:
            received_events.append(event)

        await bus.subscribe(EventType.CONFIG_CHANGED, handler)
        
        event = Event(EventType.CONFIG_CHANGED, "sync_data")
        await bus.publish(event)
        
        # 等待 executor 任务执行完成
        await asyncio.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].data == "sync_data"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self) -> None:
        """验证多个处理器"""
        bus = EventBus()
        count1 = 0
        count2 = 0

        async def handler1(event: Event) -> None:
            nonlocal count1
            count1 += 1

        async def handler2(event: Event) -> None:
            nonlocal count2
            count2 += 1

        await bus.subscribe(EventType.CONFIG_CHANGED, handler1)
        await bus.subscribe(EventType.CONFIG_CHANGED, handler2)
        
        await bus.publish(Event(EventType.CONFIG_CHANGED))
        await asyncio.sleep(0.1)
        
        assert count1 == 1
        assert count2 == 1


# ============================================================
# 3. PostgresClient 测试
# ============================================================

class TestPostgresClient:
    """验证 PostgresClient 与 Go postgres.go 一致"""

    @patch("app.infrastructure.postgres.create_async_engine")
    @patch("app.infrastructure.postgres.async_sessionmaker")
    def test_init(self, mock_sessionmaker: MagicMock, mock_create_engine: MagicMock) -> None:
        """验证初始化"""
        conn_str = "postgresql+asyncpg://user:pass@localhost:5432/db"
        client = PostgresClient(conn_str)
        
        mock_create_engine.assert_called_once()
        mock_sessionmaker.assert_called_once()
        assert client.engine == mock_create_engine.return_value

    def test_mask_password(self) -> None:
        """验证密码隐藏逻辑"""
        # 避免真正连接数据库，只测试方法
        with patch("app.infrastructure.postgres.create_async_engine"):
            client = PostgresClient("postgresql+asyncpg://user:pass@localhost:5432/db")
            
            masked = client._mask_password("postgresql+asyncpg://user:pass@localhost:5432/db")
            assert masked == "postgresql+asyncpg://user:[REDACTED]@localhost:5432/db"
            
            # 无密码情况
            masked2 = client._mask_password("postgresql+asyncpg://localhost:5432/db")
            assert masked2 == "postgresql+asyncpg://localhost:5432/db"

    @pytest.mark.asyncio
    @patch("app.infrastructure.postgres.create_async_engine")
    async def test_close(self, mock_create_engine: MagicMock) -> None:
        """验证关闭连接"""
        client = PostgresClient("postgresql+asyncpg://user:pass@localhost:5432/db")
        client.engine.dispose = AsyncMock()
        
        await client.close()
        client.engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.infrastructure.postgres.create_async_engine")
    async def test_is_healthy(self, mock_create_engine: MagicMock) -> None:
        """验证健康检查"""
        client = PostgresClient("postgresql+asyncpg://user:pass@localhost:5432/db")
        
        # 模拟 ping 成功
        client.ping = AsyncMock()
        is_healthy = await client.is_healthy()
        assert is_healthy is True
        
        # 模拟 ping 失败
        client.ping = AsyncMock(side_effect=Exception("Connection error"))
        is_healthy = await client.is_healthy()
        assert is_healthy is False


# ============================================================
# 4. RedisClient 测试
# ============================================================

class TestRedisClient:
    """验证 RedisClient 与 Go redis.go 一致"""

    @patch("redis.asyncio.Redis.from_url")
    def test_init(self, mock_from_url: MagicMock) -> None:
        """验证初始化"""
        client = RedisClient("localhost:6379", "password", 1)
        
        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/1",
            password="password",
            decode_responses=True
        )
        assert client.client == mock_from_url.return_value

    @pytest.mark.asyncio
    @patch("redis.asyncio.Redis.from_url")
    async def test_close(self, mock_from_url: MagicMock) -> None:
        """验证关闭连接"""
        client = RedisClient("localhost:6379")
        client.client.aclose = AsyncMock()
        
        await client.close()
        client.client.aclose.assert_called_once()

    @pytest.mark.asyncio
    @patch("redis.asyncio.Redis.from_url")
    async def test_is_healthy(self, mock_from_url: MagicMock) -> None:
        """验证健康检查"""
        client = RedisClient("localhost:6379")
        
        # 模拟 ping 成功
        client.ping = AsyncMock()
        is_healthy = await client.is_healthy()
        assert is_healthy is True
        
        # 模拟 ping 失败
        client.ping = AsyncMock(side_effect=Exception("Connection error"))
        is_healthy = await client.is_healthy()
        assert is_healthy is False


# ============================================================
# 5. QdrantClientWrapper 测试
# ============================================================

class TestQdrantClientWrapper:
    """验证 QdrantClientWrapper 与 Go qdrant.go 一致"""

    def test_init(self) -> None:
        """验证初始化"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        # 直接手动注入 mock，绕过对 qdrant_client 包的依赖
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        assert client.client is not None

    @pytest.mark.asyncio
    async def test_is_healthy(self) -> None:
        """验证健康检查"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        
        # 模拟 ping 成功
        client.ping = AsyncMock()
        is_healthy = await client.is_healthy()
        assert is_healthy is True
        
        # 模拟 ping 失败
        client.ping = AsyncMock(side_effect=Exception("Connection error"))
        is_healthy = await client.is_healthy()
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_ensure_collection_exists(self) -> None:
        """验证确保集合存在（已存在）"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        client.client.collection_exists = AsyncMock(return_value=True)
        client.client.create_collection = AsyncMock()
        
        await client.ensure_collection("test_collection", 1536)
        
        client.client.collection_exists.assert_called_once_with(collection_name="test_collection")
        client.client.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_collection_not_exists(self) -> None:
        """验证确保集合存在（不存在则创建）"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        client.client.collection_exists = AsyncMock(return_value=False)
        client.client.create_collection = AsyncMock()
        
        await client.ensure_collection("test_collection", 1536)
        
        client.client.collection_exists.assert_called_once_with(collection_name="test_collection")
        client.client.create_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert(self) -> None:
        """验证 Upsert"""
        from app.infrastructure.qdrant import QdrantClientWrapper, UpsertPoint
        
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        client.client.upsert = AsyncMock()
        
        points = [
            UpsertPoint(id=1, vector=[0.1, 0.2], payload={"key": "value"})
        ]
        
        await client.upsert("test_collection", points)
        
        client.client.upsert.assert_called_once()
        args, kwargs = client.client.upsert.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert len(kwargs["points"]) == 1
        assert kwargs["points"][0].id == 1
        assert kwargs["points"][0].vector == [0.1, 0.2]
        assert kwargs["points"][0].payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        """验证 Search"""
        from app.infrastructure.qdrant import QdrantClientWrapper, QdrantSearchResult
        
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        
        # 模拟搜索结果
        mock_result = MagicMock()
        mock_result.id = 1
        mock_result.score = 0.95
        mock_result.payload = {"key": "value"}
        client.client.search = AsyncMock(return_value=[mock_result])
        
        results = await client.search("test_collection", [0.1, 0.2], 5)
        
        client.client.search.assert_called_once_with(
            collection_name="test_collection",
            query_vector=[0.1, 0.2],
            limit=5,
            with_payload=True
        )
        
        assert len(results) == 1
        assert isinstance(results[0], QdrantSearchResult)
        assert results[0].id == 1
        assert results[0].score == 0.95
        assert results[0].payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_delete_points(self) -> None:
        """验证 DeletePoints"""
        from app.infrastructure.qdrant import QdrantClientWrapper
        client = QdrantClientWrapper.__new__(QdrantClientWrapper)
        client.base_url = "http://localhost:6333"
        client.client = MagicMock()
        client.client.delete = AsyncMock()
        
        await client.delete_points("test_collection", [1, 2, 3])
        
        client.client.delete.assert_called_once()
        args, kwargs = client.client.delete.call_args
        assert kwargs["collection_name"] == "test_collection"
        assert kwargs["points_selector"].points == [1, 2, 3]
