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
    CHAT_STREAM_TYPE_UNIFIED_RESPONSE,
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
    """Phase 8.5 增强后的流式回复事件载荷（旧协议，保留兼容）。"""

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


class ChatUnifiedResponsePayload(BaseModel):
    """非流式统一响应载荷。

    做什么：包含 LLM 完整回复文本、内心独白、情绪、TTS 音频地址及所有元数据，
            一次性下发给前端。
    为什么这样做：取消流式推送后，前端需要一次获取所有回复数据，按自有节奏渲染
                 Live2D 表情、气泡分段和音频播放。
    输入输出：
        - type: 固定为 "unified_response"
        - reply_text: LLM 完整回复文本（原始全文，前端自行语义切分）
        - thought_text: 内心独白文本
        - emotion: 情绪标签（如 "Happy"、"Sad" 等）
        - audio_uri: TTS 生成的音频地址（luna:// 协议），TTS 关闭或失败时为 None
        - is_finished: 固定为 True
        - schema_version: 协议版本
        - interaction_id: 交互唯一 ID
        - assistant_message_id: 助手消息 ID
        - finish_reason: 结束原因（"stop" / "length" / "error"）
        - e2e_latency_ms: 端到端延迟（毫秒），非流式模式下替代 TTFT
        - citations: 知识引用列表
        - error: 错误信息（生成正常时为空字符串）
    边界条件：
        - audio_uri 可能为 None（TTS 关闭或失败降级）
        - emotion 可能为空字符串（LLM 未返回情绪）
        - reply_text 可能为空字符串（LLM 返回空内容）
    异常行为：无。
    """
    type: str = CHAT_STREAM_TYPE_UNIFIED_RESPONSE
    reply_text: str
    thought_text: str = ""
    emotion: str = ""
    audio_uri: str | None = None
    is_finished: bool = True
    schema_version: ChatWorkflowSchemaVersion = ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1
    interaction_id: str
    assistant_message_id: str
    finish_reason: str = "stop"
    e2e_latency_ms: int = Field(default=0, ge=0)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


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
