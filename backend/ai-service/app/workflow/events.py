"""
Phase 8.5 Chat Workflow 事件协议。

做什么：定义节点状态、条件评估、流式回复和计划生命周期事件的统一信封。
为什么这样做：前端调试视图和审计链路必须能按 trace_id 解释每个节点为何进入、降级或失败。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    ChatConditionalRoute,
    ChatNodeStatus,
    ChatPlanPreset,
    ChatWorkflowEventType,
    ChatWorkflowNodeType,
    ChatWorkflowSchemaVersion,
)


class ChatConditionEvaluatedPayload(BaseModel):
    """条件边评估事件载荷。"""

    source_node_type: ChatWorkflowNodeType
    target_node_type: ChatWorkflowNodeType
    condition_entered: bool
    route_name: ChatConditionalRoute
    reason: str


class ChatNodeStatusPayload(BaseModel):
    """节点状态事件载荷。"""

    node_type: ChatWorkflowNodeType
    status: ChatNodeStatus
    started_at_ms: int | None = Field(default=None, ge=0)
    ended_at_ms: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    degraded_reason: str = ""
    error_code: str = ""


class ChatStreamChunkPayload(BaseModel):
    """Phase 8.5 增强后的流式回复事件载荷。"""

    type: str
    chunk: str
    is_finished: bool
    node_id: str
    error: str = ""
    audio_uri: str | None = None
    is_sentence_chunk: bool = False
    schema_version: ChatWorkflowSchemaVersion = ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1
    interaction_id: str
    assistant_message_id: str
    plan_preset_id: ChatPlanPreset = ChatPlanPreset.DAILY_CHAT_DEFAULT
    current_node_type: ChatWorkflowNodeType = ChatWorkflowNodeType.MAIN_CHAT_LLM
    citations: list[dict[str, Any]] = Field(default_factory=list)
    is_final_chunk: bool = False


class ChatWorkflowEvent(BaseModel):
    """Chat Workflow 基础事件信封。"""

    schema_version: ChatWorkflowSchemaVersion = ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1
    event_id: str = Field(default_factory=generate_string_id)
    event_type: ChatWorkflowEventType
    trace_id: str
    interaction_id: str
    session_id: str
    plan_preset_id: ChatPlanPreset = ChatPlanPreset.DAILY_CHAT_DEFAULT
    node_type: ChatWorkflowNodeType | None = None
    timestamp_ms: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatWorkflowEventPublisher:
    """Chat Workflow 事件发布器。"""

    async def publish(self, event: ChatWorkflowEvent) -> None:
        """
        发布事件到 SSE 管理器。

        做什么：把强类型 ChatWorkflowEvent 转换为既有 SSEManager 可广播的字典。
        为什么这样做：复用现有 SSE 通道，不让前端参与调度或状态裁决。
        异常行为：SSE 发布失败由调用方的节点观测记录，不阻断主链路。
        """
        from app.api.sse import sse_manager

        await sse_manager.publish(
            {
                "type": event.event_type.value,
                "trace_id": event.trace_id,
                "payload": event.model_dump(mode="json"),
            }
        )
