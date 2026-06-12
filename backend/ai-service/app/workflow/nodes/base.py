"""Phase 8.5 Chat Workflow 共享节点基类。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    ChatNodeStatus,
    ChatWorkflowEventType,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.events import (
    ChatNodeStatusPayload,
    ChatWorkflowEvent,
    ChatWorkflowEventPublisher,
)


class ChatWorkflowNode:
    """Chat Workflow 节点基类。"""

    def __init__(
        self,
        node_type: ChatWorkflowNodeType,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.node_type = node_type
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """子类必须实现此方法。"""
        raise NotImplementedError

    async def run_with_observation(
        self,
        state: dict[str, Any],
        handler,
    ) -> dict[str, Any]:
        """
        包装节点执行，自动记录观测数据。

        做什么：在节点执行前后自动记录 STARTED / COMPLETED / FAILED 事件和耗时。
        为什么这样做：统一观测逻辑，避免每个节点重复实现事件发布和耗时记录。
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        started_at_ms = int(time.time() * 1000)
        node_start_event = ChatWorkflowEvent(
            event_id=generate_string_id(),
            event_type=ChatWorkflowEventType.EVT_CHAT_NODE_STARTED,
            trace_id=chat_state.runtime.trace_id,
            interaction_id=chat_state.runtime.interaction_id,
            session_id=chat_state.runtime.session_id,
            plan_preset_id=chat_state.runtime.plan_preset_id,
            node_type=self.node_type,
            timestamp_ms=started_at_ms,
            payload=ChatNodeStatusPayload(
                node_type=self.node_type.value,
                status="started",
            ).model_dump(mode="json"),
        )
        chat_state.observability.emitted_event_ids.append(node_start_event.event_id)
        await self._try_publish_event(node_start_event)

        try:
            updated_state: ChatWorkflowState = await handler(chat_state)
        except Exception as exc:
            ended_at_ms = int(time.time() * 1000)
            node_failed_event = ChatWorkflowEvent(
                event_id=generate_string_id(),
                event_type=ChatWorkflowEventType.EVT_CHAT_NODE_FAILED,
                trace_id=chat_state.runtime.trace_id,
                interaction_id=chat_state.runtime.interaction_id,
                session_id=chat_state.runtime.session_id,
                plan_preset_id=chat_state.runtime.plan_preset_id,
                node_type=self.node_type,
                timestamp_ms=ended_at_ms,
                payload=ChatNodeStatusPayload(
                    node_type=self.node_type.value,
                    status="failed",
                    error_message=str(exc),
                    duration_ms=ended_at_ms - started_at_ms,
                ).model_dump(mode="json"),
            )
            chat_state.observability.emitted_event_ids.append(node_failed_event.event_id)
            await self._try_publish_event(node_failed_event)
            raise

        ended_at_ms = int(time.time() * 1000)
        completed_event = ChatWorkflowEvent(
            event_id=generate_string_id(),
            event_type=ChatWorkflowEventType.EVT_CHAT_NODE_COMPLETED,
            trace_id=updated_state.runtime.trace_id,
            interaction_id=updated_state.runtime.interaction_id,
            session_id=updated_state.runtime.session_id,
            plan_preset_id=updated_state.runtime.plan_preset_id,
            node_type=self.node_type,
            timestamp_ms=ended_at_ms,
            payload=ChatNodeStatusPayload(
                node_type=self.node_type.value,
                status="completed",
                duration_ms=ended_at_ms - started_at_ms,
                degraded=self._is_node_degraded(updated_state),
            ).model_dump(mode="json"),
        )
        updated_state.observability.emitted_event_ids.append(completed_event.event_id)
        await self._try_publish_event(completed_event)

        return updated_state.as_graph_state()

    async def _try_publish_event(self, event: ChatWorkflowEvent) -> None:
        """尝试发布事件，失败仅记录日志。"""
        if not self.event_publisher:
            return
        try:
            await self.event_publisher.publish(event)
        except Exception as exc:
            logger.warning(
                f"Chat Workflow 节点事件发布失败 trace_id={event.trace_id} "
                f"event_type={event.event_type.value} error={exc}"
            )

    def _is_node_degraded(self, state: ChatWorkflowState) -> bool:
        """判断当前节点是否处于降级状态。"""
        if self.node_type == ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG:
            return state.memory_state.degraded
        if self.node_type == ChatWorkflowNodeType.USER_PROFILE_INJECTION:
            return state.profile_state.degraded
        if self.node_type == ChatWorkflowNodeType.KNOWLEDGE_RAG:
            return state.knowledge_state.degraded
        # --- Phase 12（v3.0）新增：MCP Skill 执行节点降级检测 ---
        if self.node_type == ChatWorkflowNodeType.MCP_SKILL_EXECUTION:
            return state.mcp_tool_state.degraded
        # --- Phase 12（v3.0）新增：MCP 前置判断节点降级检测 ---
        if self.node_type == ChatWorkflowNodeType.MCP_INTENT_JUDGE:
            return state.route_state.should_enter_skill is False and state.route_state.mcp_intent == ""
        return False

    def _degraded_reason(self, state: ChatWorkflowState) -> str:
        """读取当前节点降级原因。"""
        if self.node_type == ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG:
            return state.memory_state.degraded_reason
        if self.node_type == ChatWorkflowNodeType.USER_PROFILE_INJECTION:
            return state.profile_state.degraded_reason
        if self.node_type == ChatWorkflowNodeType.KNOWLEDGE_RAG:
            return state.knowledge_state.degraded_reason
        # --- Phase 12（v3.0）新增：MCP Skill 执行节点降级原因 ---
        if self.node_type == ChatWorkflowNodeType.MCP_SKILL_EXECUTION:
            return state.mcp_tool_state.degraded_reason
        # --- Phase 12（v3.0）新增：MCP 前置判断节点降级原因 ---
        if self.node_type == ChatWorkflowNodeType.MCP_INTENT_JUDGE:
            return state.mcp_tool_state.degraded_reason or "MCP 前置判断降级"
        return ""


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
