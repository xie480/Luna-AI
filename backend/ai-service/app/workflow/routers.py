"""
Phase 8.5 Chat Workflow 条件路由模块。

做什么：集中定义长期记忆 RAG 与知识库 RAG 条件边评估、旁路汇合节点和条件事件发送。
为什么这样做：条件节点未进入不是静默跳过，必须记录 NOT_ENTERED_BY_CONDITION 与 EVT_CHAT_CONDITION_EVALUATED。
"""

from __future__ import annotations

import time
from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
    CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
    ChatConditionalRoute,
    ChatNodeStatus,
    ChatWorkflowEventType,
    ChatWorkflowGraphNodeName,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatNodeObservation, ChatWorkflowState
from app.workflow.events import ChatConditionEvaluatedPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher


class ChatWorkflowRouter:
    """Chat Workflow 条件路由器。"""

    def __init__(self, event_publisher: ChatWorkflowEventPublisher | None = None):
        """绑定事件发布器，供条件边评估时输出调试事件。"""
        self.event_publisher = event_publisher

    async def route_long_term_memory(self, graph_state: dict[str, Any]) -> str:
        """评估是否进入长期记忆 RAG 条件节点。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_long_term_memory_rag
        reason = _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON)
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.SESSION_CONTEXT_LOAD,
            target_node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_LONG_TERM_MEMORY_RAG
                if entered
                else ChatConditionalRoute.BYPASS_LONG_TERM_MEMORY_RAG
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value
            if entered
            else ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value
        )

    async def route_knowledge_rag(self, graph_state: dict[str, Any]) -> str:
        """评估是否进入知识库 RAG 条件节点。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_knowledge_rag
        reason = _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON)
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.USER_PROFILE_INJECTION,
            target_node_type=ChatWorkflowNodeType.KNOWLEDGE_RAG,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_KNOWLEDGE_RAG
                if entered
                else ChatConditionalRoute.BYPASS_KNOWLEDGE_RAG
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value
            if entered
            else ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value
        )

    async def bypass_long_term_memory(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """长期记忆条件未进入时写入显式观测记录并汇合。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        _append_not_entered_observation(
            state,
            ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON),
        )
        return state.as_graph_state()

    async def bypass_knowledge_rag(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """知识库 RAG 条件未进入时写入显式观测记录并汇合。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        _append_not_entered_observation(
            state,
            ChatWorkflowNodeType.KNOWLEDGE_RAG,
            _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON),
        )
        return state.as_graph_state()

    async def _publish_condition(
        self,
        *,
        state: ChatWorkflowState,
        source_node_type: ChatWorkflowNodeType,
        target_node_type: ChatWorkflowNodeType,
        condition_entered: bool,
        route_name: ChatConditionalRoute,
        reason: str,
    ) -> None:
        """发布条件评估事件并记录日志。"""
        payload = ChatConditionEvaluatedPayload(
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            condition_entered=condition_entered,
            route_name=route_name,
            reason=reason,
        )
        logger.info(
            f"Chat Workflow 条件边评估 trace_id={state.runtime.trace_id} "
            f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} "
            f"source_node_type={source_node_type.value} target_node_type={target_node_type.value} "
            f"condition_entered={condition_entered} route_name={route_name.value} reason={reason}"
        )
        if not self.event_publisher:
            return
        event = ChatWorkflowEvent(
            event_id=generate_string_id(),
            event_type=ChatWorkflowEventType.EVT_CHAT_CONDITION_EVALUATED,
            trace_id=state.runtime.trace_id,
            interaction_id=state.runtime.interaction_id,
            session_id=state.runtime.session_id,
            plan_preset_id=state.runtime.plan_preset_id,
            node_type=target_node_type,
            timestamp_ms=_now_ms(),
            payload=payload.model_dump(mode="json"),
        )
        state.observability.emitted_event_ids.append(event.event_id)
        try:
            await self.event_publisher.publish(event)
        except Exception as exc:
            logger.warning(f"条件评估事件发布失败 trace_id={state.runtime.trace_id} error={exc}")


def _append_not_entered_observation(
    state: ChatWorkflowState,
    node_type: ChatWorkflowNodeType,
    reason: str,
) -> None:
    """写入条件未进入节点观测。"""
    now_ms = _now_ms()
    state.observability.node_observations.append(
        ChatNodeObservation(
            node_type=node_type,
            status=ChatNodeStatus.NOT_ENTERED_BY_CONDITION,
            started_at_ms=now_ms,
            ended_at_ms=now_ms,
            latency_ms=0,
            retry_count=state.runtime.retry_count,
            condition_entered=False,
            condition_reason=reason,
        )
    )


def _first_reason(reasons: list[str], fallback: str) -> str:
    """读取首个非空原因。"""
    for reason in reasons:
        if reason:
            return reason
    return fallback


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
