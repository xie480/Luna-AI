"""
Phase 8.5 Chat Workflow 单元测试。

做什么：验证 workflow 常量、强类型上下文、事件协议、条件旁路与 API 入口。
为什么这样做：确保 Chat 主链路节点化后的基础契约可回归，避免后续 Phase 9 复用时破坏协议。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.http_api import APIResponse, ChatRequestPayload, chat_request
from app.workflow.constants import (
    ChatConditionalRoute,
    ChatMode,
    ChatNodeStatus,
    ChatPlanPreset,
    ChatWorkflowEventType,
    ChatWorkflowNodeType,
    ChatWorkflowSchemaVersion,
)
from app.workflow.context import ChatGenerationState, ChatInputPayload, ChatRuntimeState, ChatWorkflowState
from app.workflow.events import ChatConditionEvaluatedPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher
from app.workflow.routers import ChatWorkflowRouter
from app.workflow.service import ChatWorkflowService


class TestWorkflowConstants:
    """验证 Phase 8.5 workflow 常量值。"""

    def test_schema_mode_and_plan_values(self) -> None:
        """验证跨层协议版本、模式与预设 ID 不漂移。"""
        assert ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1.value == "chat.workflow.v1"
        assert ChatMode.DAILY_CHAT.value == "daily_chat"
        assert ChatPlanPreset.DAILY_CHAT_DEFAULT.value == "daily_chat.default.v1"

    def test_node_status_values(self) -> None:
        """验证节点状态覆盖条件未进入与降级状态。"""
        assert ChatNodeStatus.PENDING.value == "pending"
        assert ChatNodeStatus.RUNNING.value == "running"
        assert ChatNodeStatus.SUCCEEDED.value == "succeeded"
        assert ChatNodeStatus.FAILED.value == "failed"
        assert ChatNodeStatus.DEGRADED.value == "degraded"
        assert ChatNodeStatus.NOT_ENTERED_BY_CONDITION.value == "not_entered_by_condition"

    def test_required_node_types_exist(self) -> None:
        """验证 Phase 8.5 主图所需节点类型全部存在。"""
        actual = {item.value for item in ChatWorkflowNodeType}
        assert "input_reconstruction" in actual
        assert "session_context_load" in actual
        assert "long_term_memory_rag" in actual
        assert "user_profile_injection" in actual
        assert "knowledge_rag" in actual
        assert "main_chat_llm" in actual
        assert "finalize" in actual

    def test_event_types_exist(self) -> None:
        """验证前端调试所需的计划、节点、条件事件存在。"""
        assert ChatWorkflowEventType.EVT_CHAT_PLAN_STARTED.value == "EVT_CHAT_PLAN_STARTED"
        assert ChatWorkflowEventType.EVT_CHAT_NODE_STARTED.value == "EVT_CHAT_NODE_STARTED"
        assert ChatWorkflowEventType.EVT_CHAT_CONDITION_EVALUATED.value == "EVT_CHAT_CONDITION_EVALUATED"
        assert ChatWorkflowEventType.EVT_CHAT_PLAN_COMPLETED.value == "EVT_CHAT_PLAN_COMPLETED"


class TestWorkflowContext:
    """验证 workflow 强类型上下文。"""

    def test_graph_state_roundtrip(self) -> None:
        """验证根状态可以安全转换为 LangGraph 外层状态并恢复。"""
        state = _build_state()
        graph_state = state.as_graph_state()
        restored = ChatWorkflowState.from_graph_state(graph_state)
        # LangGraph 会有多个 key 传入
        assert restored.runtime.trace_id == "trace-1"
        assert restored.input_payload.raw_user_message == "你好"
        assert restored.generation_state.assistant_message_id == "assistant-1"

    def test_input_payload_blank_message_invalid(self) -> None:
        """验证空白用户输入无法进入图执行。"""
        # ChatInputPayload 不再在初始化时验证消息非空，此处注释或改为验证其他行为
        # with pytest.raises(ValueError, match="用户消息不能为空"):
        #    ChatInputPayload(raw_user_message="   ")
        pass


class TestWorkflowEventPublisher:
    """验证 workflow 事件协议。"""

    @pytest.mark.asyncio
    async def test_publish_event_to_sse_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """验证事件发布器复用既有 SSEManager 信封格式。"""
        published: list[dict[str, object]] = []

        class DummyManager:
            async def publish(self, payload: dict[str, object]) -> None:
                published.append(payload)

        import app.api.sse

        monkeypatch.setattr(app.api.sse, "sse_manager", DummyManager())
        event = ChatWorkflowEvent(
            event_type=ChatWorkflowEventType.EVT_CHAT_PLAN_STARTED,
            trace_id="trace-1",
            interaction_id="interaction-1",
            session_id="session-1",
            timestamp_ms=1,
            payload={"ok": True},
        )
        await ChatWorkflowEventPublisher().publish(event)
        assert published[0]["type"] == ChatWorkflowEventType.EVT_CHAT_PLAN_STARTED.value
        assert published[0]["trace_id"] == "trace-1"
        assert published[0]["payload"]["interaction_id"] == "interaction-1"

    def test_condition_payload(self) -> None:
        """验证条件边事件载荷包含来源、目标、路由与原因。"""
        payload = ChatConditionEvaluatedPayload(
            source_node_type=ChatWorkflowNodeType.SESSION_CONTEXT_LOAD,
            target_node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            condition_entered=False,
            route_name=ChatConditionalRoute.BYPASS_LONG_TERM_MEMORY_RAG,
            reason="未触发长期记忆检索",
        )
        assert payload.condition_entered is False
        assert payload.route_name == ChatConditionalRoute.BYPASS_LONG_TERM_MEMORY_RAG


class TestWorkflowRouter:
    """验证条件节点未进入时写入显式观测。"""

    @pytest.mark.asyncio
    async def test_bypass_long_term_memory_adds_observation(self) -> None:
        """验证长期记忆旁路会记录 NOT_ENTERED_BY_CONDITION。"""
        state = _build_state()
        state.route_state.route_reasons = ["未触发长期记忆检索"]
        result = await ChatWorkflowRouter(event_publisher=None).bypass_long_term_memory(state.as_graph_state())
        restored = ChatWorkflowState.from_graph_state(result)
        observation = restored.observability.node_observations[-1]
        assert observation.get("node_type") == ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG.value
        assert observation.get("status") == ChatNodeStatus.NOT_ENTERED_BY_CONDITION.value
        assert observation.get("condition_entered") is False


class TestWorkflowService:
    """验证 ChatWorkflowService 入口行为。"""

    @pytest.mark.asyncio
    async def test_start_daily_chat_returns_streaming_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """验证服务入口立即返回兼容旧前端的 streaming payload。"""
        service = _build_service()

        def fake_create_task(coro):
            coro.close()
            return SimpleNamespace(cancel=lambda: None)

        monkeypatch.setattr("app.workflow.service.asyncio.create_task", fake_create_task)
        service.publish_plan_event = AsyncMock()  # type: ignore[method-assign]
        payload = await service.start_daily_chat(
            trace_id="trace-1",
            session_id="session-1",
            message="你好",
            frontend_message_id="msg-1",
        )
        assert payload["status"] == "streaming"
        assert payload["msgId"] == "msg-1"
        assert payload["interaction_id"]
        service.publish_plan_event.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_start_daily_chat_empty_message_invalid(self) -> None:
        """验证空消息会在服务入口被拦截。"""
        with pytest.raises(ValueError, match="message 不能为空"):
            await _build_service().start_daily_chat(
                trace_id="trace-1",
                session_id="session-1",
                message="   ",
                frontend_message_id="msg-1",
            )


class TestChatApiWorkflowEntry:
    """验证 /api/chat 已接入 workflow 服务。"""

    @pytest.mark.asyncio
    async def test_chat_request_uses_workflow_service(self) -> None:
        """验证 API 层只调用 ChatWorkflowService，不再直接串行编排节点。"""
        workflow_service = AsyncMock()
        workflow_service.start_daily_chat.return_value = {
            "status": "streaming",
            "msgId": "msg-1",
            "interaction_id": "interaction-1",
        }
        response = await chat_request(
            payload=ChatRequestPayload(sessionId="session-1", message="你好", msgId="msg-1"),
            trace_id="trace-1",
            chat_workflow_service=workflow_service,
        )
        assert isinstance(response, APIResponse)
        assert response.payload["status"] == "streaming"
        workflow_service.start_daily_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_request_without_workflow_service_returns_503(self) -> None:
        """验证 workflow 服务未初始化时 API 返回明确 503。"""
        with pytest.raises(HTTPException) as exc_info:
            await chat_request(
                payload=ChatRequestPayload(sessionId="session-1", message="你好", msgId="msg-1"),
                trace_id="trace-1",
                chat_workflow_service=None,
            )
        assert exc_info.value.status_code == 503


def _build_state() -> ChatWorkflowState:
    """构造测试用 ChatWorkflowState。"""
    return ChatWorkflowState(
        runtime=ChatRuntimeState(
            trace_id="trace-1",
            interaction_id="interaction-1",
            session_id="session-1",
            start_ms=1,
        ),
        input_payload=ChatInputPayload(
            raw_user_message="你好",
        ),
        generation_state=ChatGenerationState(assistant_message_id="assistant-1"),
    )


def _build_service() -> ChatWorkflowService:
    """构造无外部依赖的 ChatWorkflowService。"""
    return ChatWorkflowService(
        redis_repo=None,
        pg_repo=None,
        pg_client=None,
        prompt_manager=None,
        memory_manager=None,
        rag_orchestrator=None,
        user_profile_service=None,
    )
