"""Phase 8.5 workflow 状态模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.rag.types import RagEvidence
from app.repository.chat_history_redis import Interaction
from app.types.constants import RagRetrievalRoute
from app.workflow.constants import (
    CHAT_WORKFLOW_CONTEXT_WINDOW_READY,
    CHAT_WORKFLOW_DEFAULT_LOCALE,
    CHAT_WORKFLOW_DEFAULT_TIMEZONE,
    CHAT_WORKFLOW_DEFAULT_USER_ID,
    ChatMode,
    ChatNodeStatus,
    ChatPlanPreset,
    ChatWorkflowNodeType,
    ChatWorkflowSchemaVersion,
)


class KnowledgeCitation(BaseModel):
    """知识引用视图。"""

    citation_id: int | str = ""
    document_id: str = ""
    document_name: str = ""
    chunk_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRuntimeContext(BaseModel):
    """运行态上下文。"""

    trace_id: str = Field(min_length=1, max_length=64)
    interaction_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(default=CHAT_WORKFLOW_DEFAULT_USER_ID, min_length=1, max_length=64)
    chat_mode: ChatMode = ChatMode.DAILY_CHAT
    plan_preset_id: ChatPlanPreset = ChatPlanPreset.DAILY_CHAT_DEFAULT
    current_node_type: ChatWorkflowNodeType | None = None
    started_at_ms: int = Field(ge=0)
    deadline_at_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)


class ChatInputPayload(BaseModel):
    """本轮输入载荷。"""

    raw_user_message: str = Field(min_length=1, max_length=20000)
    frontend_message_id: str = Field(min_length=1, max_length=64)
    client_timestamp_ms: int = Field(ge=0)
    locale: str = Field(default=CHAT_WORKFLOW_DEFAULT_LOCALE, min_length=1, max_length=32)
    timezone: str = Field(default=CHAT_WORKFLOW_DEFAULT_TIMEZONE, min_length=1, max_length=64)

    @field_validator("raw_user_message")
    @classmethod
    def validate_raw_user_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("用户消息不能为空")
        return cleaned


class ChatSessionState(BaseModel):
    """会话窗口状态。"""

    recent_messages: list[Interaction] = Field(default_factory=list)
    short_summary: str = ""
    key_facts: list[str] = Field(default_factory=list)
    token_budget_total: int = Field(default=0, ge=0)
    token_budget_used: int = Field(default=0, ge=0)
    context_window_status: str = CHAT_WORKFLOW_CONTEXT_WINDOW_READY
    memory_snippets: str = ""


class ChatRouteState(BaseModel):
    """输入重构与路由状态。"""

    reconstructed_text: str = ""
    disambiguated_text: str = ""
    user_intent_summary: str = ""
    search_queries: list[str] = Field(default_factory=list)
    entity_mentions: list[str] = Field(default_factory=list)
    temporal_focus: dict[str, Any] = Field(default_factory=dict)
    should_enter_long_term_memory_rag: bool = False
    should_enter_knowledge_rag: bool = False
    route_reasons: list[str] = Field(default_factory=list)
    external_search_queries: list[str] = Field(default_factory=list)
    external_entity_mentions: list[str] = Field(default_factory=list)
    external_temporal_focus: dict[str, Any] = Field(default_factory=dict)
    knowledge_route: RagRetrievalRoute = RagRetrievalRoute.HYBRID
    emotion_state: dict[str, Any] = Field(default_factory=dict)


class ChatMemoryState(BaseModel):
    """长期记忆状态。"""

    entered_by_condition: bool = False
    condition_reason: str = ""
    prompt_memory_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatUserProfileState(BaseModel):
    """用户画像状态。"""

    injection_executed: bool = False
    prompt_profile_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatKnowledgeRagState(BaseModel):
    """知识库 RAG 状态。"""

    entered_by_condition: bool = False
    condition_reason: str = ""
    retrieval_route: str = ""
    evidences: list[RagEvidence] = Field(default_factory=list)
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    prompt_knowledge_text: str = ""
    degraded: bool = False
    degraded_reason: str = ""


class ChatPromptState(BaseModel):
    """Prompt 装配结果。"""

    system_prompt_text: str = ""
    prompt_variables: dict[str, str] = Field(default_factory=dict)


class ChatGenerationState(BaseModel):
    """主模型生成状态。"""

    assistant_message_id: str = Field(min_length=1, max_length=64)
    model_name: str = ""
    provider_name: str = ""
    stream_started_at_ms: int | None = Field(default=None, ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    full_text: str = ""
    thought_text: str = ""
    emotion: str = ""
    finish_reason: str = ""
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    error: str = ""


class ChatNodeObservation(BaseModel):
    """节点观测记录。"""

    node_type: ChatWorkflowNodeType
    status: ChatNodeStatus
    started_at_ms: int = Field(ge=0)
    ended_at_ms: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    condition_entered: bool | None = None
    condition_reason: str = ""
    degraded_reason: str = ""
    error_code: str = ""


class ChatObservabilityState(BaseModel):
    """可观测状态。"""

    node_observations: list[ChatNodeObservation] = Field(default_factory=list)
    emitted_event_ids: list[str] = Field(default_factory=list)


class ChatErrorState(BaseModel):
    """主链路错误状态。"""

    node_type: ChatWorkflowNodeType
    error_code: str
    message: str
    retryable: bool = False
    recoverable: bool = False


class ChatWorkflowState(BaseModel):
    """Workflow 根状态。"""

    schema_version: ChatWorkflowSchemaVersion = ChatWorkflowSchemaVersion.CHAT_WORKFLOW_V1
    runtime: ChatRuntimeContext
    input_payload: ChatInputPayload
    session_state: ChatSessionState = Field(default_factory=ChatSessionState)
    route_state: ChatRouteState = Field(default_factory=ChatRouteState)
    memory_state: ChatMemoryState = Field(default_factory=ChatMemoryState)
    profile_state: ChatUserProfileState = Field(default_factory=ChatUserProfileState)
    knowledge_state: ChatKnowledgeRagState = Field(default_factory=ChatKnowledgeRagState)
    prompt_state: ChatPromptState = Field(default_factory=ChatPromptState)
    generation_state: ChatGenerationState
    observability: ChatObservabilityState = Field(default_factory=ChatObservabilityState)
    error_state: ChatErrorState | None = None

    def as_graph_state(self) -> dict[str, Any]:
        return {"state": self.model_dump(mode="json")}

    @classmethod
    def from_graph_state(cls, value: dict[str, Any] | ChatWorkflowState) -> ChatWorkflowState:
        if isinstance(value, ChatWorkflowState):
            return value
        if "state" in value and isinstance(value["state"], dict):
            return cls.model_validate(value["state"])
        return cls.model_validate(value)
