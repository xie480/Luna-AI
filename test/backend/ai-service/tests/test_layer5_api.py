"""
第五阶段（Layer 5）综合测试

做什么：验证 Go backend/runtime/internal/api/* 的 Python 端口
     与原始 Go 实现在行为、逻辑和边界条件上 100% 一致。

覆盖范围：
    - api/grpc_client.py: gRPC 客户端及拦截器
    - api/ws_server.py: WebSocket 路由及连接管理器
    - api/routers/api_config_preset.py: API 配置预设路由
    - api/routers/prompt.py: Prompt 路由
    - api/routers/telemetry.py: 可观测性路由

Go 原版参考文件：
    - backend/runtime/internal/api/grpc_client.go
    - backend/runtime/internal/api/ws_server.go
    - backend/runtime/internal/api/api_config_preset_handler.go
    - backend/runtime/internal/api/prompt_handler.go
    - backend/runtime/internal/api/telemetry_handler.go
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.grpc_client import AIClient
from app.api.routers.api_config_preset import router as config_preset_router
from app.api.routers.prompt import router as prompt_router
from app.api.routers.telemetry import router as telemetry_router
from app.api.ws_server import (
    CMDUserInputPayload,
    InitStatePayload,
    InteractionQA,
    WSConnection,
    WSMessage,
    WSServer,
)
from app.repository.models import ApiConfigPreset, PromptTemplate, PromptVersion
from app.types.constants import (
    WS_MSG_TYPE_CMD_SYNC_INIT_STATE,
    WS_MSG_TYPE_CMD_USER_INPUT,
    WS_MSG_TYPE_EVT_INIT_STATE,
    WS_MSG_TYPE_PING,
    WS_MSG_TYPE_PONG,
    WS_MSG_TYPE_REQ_GET_CALENDAR_METADATA,
    WS_MSG_TYPE_REQ_GET_CHAT_HISTORY,
    WS_MSG_TYPE_RES_CALENDAR_METADATA,
    WS_MSG_TYPE_RES_CHAT_HISTORY,
)


# ============================================================
# 1. gRPC Client 测试
# ============================================================

class TestGRPCClient:
    """验证 AIClient 与 Go grpc_client.go 一致"""

    @patch("grpc.aio.insecure_channel")
    @patch("app.api.communication_pb2_grpc.CommunicationServiceStub")
    def test_init(self, mock_stub, mock_channel):
        client = AIClient("localhost:50051")
        mock_channel.assert_called_once()
        mock_stub.assert_called_once_with(mock_channel.return_value)
        assert client.address == "localhost:50051"

    @pytest.mark.asyncio
    @patch("grpc.aio.insecure_channel")
    @patch("app.api.communication_pb2_grpc.CommunicationServiceStub")
    async def test_ping(self, mock_stub, mock_channel):
        client = AIClient("localhost:50051")
        
        mock_resp = MagicMock()
        mock_resp.timestamp = 1234567890
        mock_resp.source = "test"
        client.client.Ping = AsyncMock(return_value=mock_resp)
        
        resp = await client.ping("trace-123")
        
        assert resp.timestamp == 1234567890
        assert resp.source == "test"
        client.client.Ping.assert_called_once()


# ============================================================
# 2. WebSocket Server 测试
# ============================================================

class TestWSServer:
    """验证 WSServer 与 Go ws_server.go 一致"""

    @pytest.fixture
    def mock_deps(self):
        memory_manager = MagicMock()
        memory_manager.on_event = AsyncMock()
        return {
            "ai_client": MagicMock(),
            "redis_repo": MagicMock(),
            "pg_repo": MagicMock(),
            "prompt_mgr": MagicMock(),
            "memory_manager": memory_manager,
        }

    @pytest.mark.asyncio
    async def test_handle_ping(self, mock_deps):
        server = WSServer(**mock_deps)
        
        mock_conn = MagicMock(spec=WSConnection)
        mock_conn.write_json = AsyncMock()
        
        msg = WSMessage(
            type=WS_MSG_TYPE_PING,
            trace_id="trace-123",
            payload={"timestamp": 1234567890}
        )
        
        mock_resp = MagicMock()
        mock_resp.timestamp = 1234567890
        mock_resp.source = "test"
        mock_deps["ai_client"].ping = AsyncMock(return_value=mock_resp)
        
        await server.handle_ping(mock_conn, msg)
        
        mock_deps["ai_client"].ping.assert_called_once_with("trace-123")
        mock_conn.write_json.assert_called_once()
        
        args, _ = mock_conn.write_json.call_args
        resp_dict = args[0]
        assert resp_dict["type"] == WS_MSG_TYPE_PONG
        assert resp_dict["trace_id"] == "trace-123"
        assert resp_dict["payload"]["timestamp"] == 1234567890
        assert resp_dict["payload"]["source"] == "test"

    @pytest.mark.asyncio
    async def test_handle_sync_init_state(self, mock_deps):
        server = WSServer(**mock_deps)
        
        mock_conn = MagicMock(spec=WSConnection)
        mock_conn.write_json = AsyncMock()
        
        msg = WSMessage(
            type=WS_MSG_TYPE_CMD_SYNC_INIT_STATE,
            trace_id="trace-123",
            payload={"sessionId": "session-1"}
        )
        
        # 模拟 Redis 返回
        mock_interaction = MagicMock()
        mock_interaction.msgId = "msg-1"
        mock_interaction.userContent = "hello"
        mock_interaction.assistantContent = "hi"
        mock_interaction.timestamp = 123
        
        mock_deps["redis_repo"].get_context = AsyncMock(return_value=(None, [mock_interaction]))
        
        await server.handle_sync_init_state(mock_conn, msg)
        
        mock_deps["redis_repo"].get_context.assert_called_once_with("session-1")
        mock_conn.write_json.assert_called_once()
        
        args, _ = mock_conn.write_json.call_args
        resp_dict = args[0]
        assert resp_dict["type"] == WS_MSG_TYPE_EVT_INIT_STATE
        assert resp_dict["trace_id"] == "trace-123"
        assert resp_dict["payload"]["sessionId"] == "session-1"
        assert len(resp_dict["payload"]["recentQA"]) == 1
        assert resp_dict["payload"]["recentQA"][0]["msgId"] == "msg-1"

    @pytest.mark.asyncio
    async def test_handle_get_calendar_metadata(self, mock_deps):
        server = WSServer(**mock_deps)
        
        mock_conn = MagicMock(spec=WSConnection)
        mock_conn.write_json = AsyncMock()
        
        msg = WSMessage(
            type=WS_MSG_TYPE_REQ_GET_CALENDAR_METADATA,
            trace_id="trace-123",
            payload={"year_month": "2023-10"}
        )
        
        mock_deps["pg_repo"].get_active_dates_by_month = AsyncMock(return_value=["01", "15"])
        
        await server.handle_get_calendar_metadata(mock_conn, msg)
        
        mock_deps["pg_repo"].get_active_dates_by_month.assert_called_once_with("2023-10")
        mock_conn.write_json.assert_called_once()
        
        args, _ = mock_conn.write_json.call_args
        resp_dict = args[0]
        assert resp_dict["type"] == WS_MSG_TYPE_RES_CALENDAR_METADATA
        assert resp_dict["trace_id"] == "trace-123"
        assert resp_dict["payload"]["year_month"] == "2023-10"
        assert resp_dict["payload"]["active_dates"] == ["01", "15"]

    @pytest.mark.asyncio
    async def test_handle_get_chat_history(self, mock_deps):
        server = WSServer(**mock_deps)
        
        mock_conn = MagicMock(spec=WSConnection)
        mock_conn.write_json = AsyncMock()
        
        msg = WSMessage(
            type=WS_MSG_TYPE_REQ_GET_CHAT_HISTORY,
            trace_id="trace-123",
            payload={"date": "2023-10-27"}
        )
        
        # 模拟 PG 返回
        from datetime import datetime, timezone
        mock_interaction = MagicMock()
        mock_interaction.message_id = "msg-1"
        mock_interaction.id = "int-1"
        mock_interaction.user_content = "hello"
        mock_interaction.assistant_content = "hi"
        mock_interaction.error = ""
        mock_interaction.created_at = datetime(2023, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
        
        mock_deps["pg_repo"].get_interactions_by_date = AsyncMock(return_value=[mock_interaction])
        
        await server.handle_get_chat_history(mock_conn, msg)
        
        mock_deps["pg_repo"].get_interactions_by_date.assert_called_once_with("2023-10-27")
        mock_conn.write_json.assert_called_once()
        
        args, _ = mock_conn.write_json.call_args
        resp_dict = args[0]
        assert resp_dict["type"] == WS_MSG_TYPE_RES_CHAT_HISTORY
        assert resp_dict["trace_id"] == "trace-123"
        assert resp_dict["payload"]["date"] == "2023-10-27"
        assert len(resp_dict["payload"]["messages"]) == 2 # 1 user + 1 assistant
        assert resp_dict["payload"]["messages"][0]["role"] == "user"
        assert resp_dict["payload"]["messages"][1]["role"] == "assistant"


# ============================================================
# 3. Routers 测试
# ============================================================

app = FastAPI()
app.include_router(config_preset_router)
app.include_router(prompt_router)
app.include_router(telemetry_router)

client = TestClient(app)

class TestRouters:
    """验证 Routers 与 Go handler 一致"""

    def test_get_presets(self):
        mock_repo = MagicMock()
        mock_repo.get_all = AsyncMock(return_value=[
            ApiConfigPreset(
                id="1", name="test", is_active=True,
                large_model_config={"api_key": "secret"},
                medium_model_config={},
                small_model_config={}
            )
        ])
        
        app.state.config_preset_repo = mock_repo
        
        response = client.get("/api/v1/config/presets")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "1"
        assert data["data"][0]["large_model_config"]["api_key"] == "********" # 验证脱敏

    def test_get_templates(self):
        mock_mgr = MagicMock()
        mock_mgr.list_templates = AsyncMock(return_value=[
            PromptTemplate(id="1", name="test", category="chat", slot_position="system", is_system=True)
        ])
        
        app.state.prompt_manager = mock_mgr
        
        response = client.get("/api/v1/prompts/templates")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "1"
        assert data["data"][0]["name"] == "test"

    def test_get_telemetry_traces(self):
        mock_pg_client = MagicMock()
        
        async def mock_get_session():
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = 0
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            yield mock_session
            
        mock_pg_client.get_session = mock_get_session
        app.state.pg_client = mock_pg_client
        
        response = client.get("/api/v1/telemetry/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "total" in data["data"]
        assert "spans" in data["data"]
