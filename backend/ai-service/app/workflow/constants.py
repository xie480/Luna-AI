"""
Phase 8.5 Chat Workflow 常量模块。

做什么：集中定义日常闲聊 LangGraph 主链路使用的 schema、模式、节点、状态、事件、路由与 Prompt 槽位常量。
为什么这样做：Phase 8.5 要求禁止魔法字符串，所有跨节点、跨层通信字段必须有统一命名来源。
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class ChatWorkflowSchemaVersion(str, Enum):
    """Chat Workflow 事件与状态协议版本。"""

    CHAT_WORKFLOW_V1 = "chat.workflow.v1"


class ChatMode(str, Enum):
    """当前 Phase 8.5 支持的 Chat 模式。"""

    DAILY_CHAT = "daily_chat"


class ChatPlanPreset(str, Enum):
    """内置 Chat Plan 预设标识。"""

    DAILY_CHAT_DEFAULT = "daily_chat.default.v1"


class ChatWorkflowNodeType(str, Enum):
    """Chat 主链路节点类型枚举。"""

    MESSAGE_INGRESS = "message_ingress"
    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    LONG_TERM_MEMORY_RAG = "long_term_memory_rag"
    USER_PROFILE_INJECTION = "user_profile_injection"
    KNOWLEDGE_RAG = "knowledge_rag"
    CONTEXT_GOVERNANCE = "context_governance"
    PROMPT_ASSEMBLY = "prompt_assembly"
    MAIN_CHAT_LLM = "main_chat_llm"
    RESPONSE_PERSISTENCE = "response_persistence"
    LONG_TERM_MEMORY_COMPRESSION = "long_term_memory_compression"
    USER_PROFILE_EXTRACTION = "user_profile_extraction"
    POSTPROCESS_COMMIT = "postprocess_commit"
    ERROR_RECOVERY = "error_recovery"
    FINALIZE = "finalize"


class ChatNodeStatus(str, Enum):
    """Chat 节点运行状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"
    NOT_ENTERED_BY_CONDITION = "not_entered_by_condition"


class ChatConditionalRoute(str, Enum):
    """Chat 条件边路由结果枚举。"""

    ENTER_LONG_TERM_MEMORY_RAG = "enter_long_term_memory_rag"
    BYPASS_LONG_TERM_MEMORY_RAG = "bypass_long_term_memory_rag"
    ENTER_KNOWLEDGE_RAG = "enter_knowledge_rag"
    BYPASS_KNOWLEDGE_RAG = "bypass_knowledge_rag"
    ENTER_POSTPROCESS = "enter_postprocess"
    ENTER_ERROR_RECOVERY = "enter_error_recovery"


class ChatWorkflowEventType(str, Enum):
    """Chat Workflow 对外事件类型枚举。"""

    EVT_CHAT_PLAN_STARTED = "EVT_CHAT_PLAN_STARTED"
    EVT_CHAT_NODE_STARTED = "EVT_CHAT_NODE_STARTED"
    EVT_CHAT_NODE_COMPLETED = "EVT_CHAT_NODE_COMPLETED"
    EVT_CHAT_NODE_FAILED = "EVT_CHAT_NODE_FAILED"
    EVT_CHAT_NODE_DEGRADED = "EVT_CHAT_NODE_DEGRADED"
    EVT_CHAT_CONDITION_EVALUATED = "EVT_CHAT_CONDITION_EVALUATED"
    EVT_CHAT_STREAM_CHUNK = "EVT_CHAT_STREAM_CHUNK"
    EVT_CHAT_POSTPROCESS_STARTED = "EVT_CHAT_POSTPROCESS_STARTED"
    EVT_CHAT_POSTPROCESS_COMPLETED = "EVT_CHAT_POSTPROCESS_COMPLETED"
    EVT_CHAT_PLAN_COMPLETED = "EVT_CHAT_PLAN_COMPLETED"


class ChatWorkflowErrorCode(str, Enum):
    """Chat Workflow 内部错误码，供节点观测与错误恢复使用。"""

    INVALID_CHAT_INPUT = "CHAT_WORKFLOW_INVALID_CHAT_INPUT"
    PROMPT_ASSEMBLY_FAILED = "CHAT_WORKFLOW_PROMPT_ASSEMBLY_FAILED"
    MAIN_LLM_FAILED = "CHAT_WORKFLOW_MAIN_LLM_FAILED"
    PERSISTENCE_DEGRADED = "CHAT_WORKFLOW_PERSISTENCE_DEGRADED"
    NODE_UNEXPECTED_FAILED = "CHAT_WORKFLOW_NODE_UNEXPECTED_FAILED"
    CHECKPOINT_WRITE_FAILED = "CHAT_WORKFLOW_CHECKPOINT_WRITE_FAILED"


class ChatWorkflowGraphNodeName(str, Enum):
    """LangGraph 内部节点名称。"""

    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    LONG_TERM_MEMORY_RAG = "long_term_memory_rag"
    LONG_TERM_MEMORY_BYPASS = "long_term_memory_bypass"
    USER_PROFILE_INJECTION = "user_profile_injection"
    KNOWLEDGE_RAG = "knowledge_rag"
    KNOWLEDGE_RAG_BYPASS = "knowledge_rag_bypass"
    CONTEXT_GOVERNANCE = "context_governance"
    PROMPT_ASSEMBLY = "prompt_assembly"
    MAIN_CHAT_LLM = "main_chat_llm"
    RESPONSE_PERSISTENCE = "response_persistence"
    LONG_TERM_MEMORY_COMPRESSION = "long_term_memory_compression"
    USER_PROFILE_EXTRACTION = "user_profile_extraction"
    POSTPROCESS_COMMIT = "postprocess_commit"
    FINALIZE = "finalize"


CHAT_WORKFLOW_CHECKPOINT_TABLE: Final[str] = "langgraph_chat_checkpoints"
CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR: Final[str] = ":"
CHAT_WORKFLOW_DEFAULT_LOCALE: Final[str] = "zh-CN"
CHAT_WORKFLOW_DEFAULT_TIMEZONE: Final[str] = "Asia/Shanghai"
CHAT_WORKFLOW_DEFAULT_USER_ID: Final[str] = "local_default_user"
CHAT_WORKFLOW_CONTEXT_WINDOW_READY: Final[str] = "ready"
CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED: Final[str] = "degraded"
CHAT_WORKFLOW_EMPTY_PROFILE_REASON: Final[str] = "用户画像为空，已输出显式空画像槽位"
CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON: Final[str] = "输入重构结果未触发长期记忆检索"
CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON: Final[str] = "输入重构结果未触发知识库检索"
CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON: Final[str] = "输入重构失败，已使用原始输入与保守规则路由降级"
CHAT_WORKFLOW_POSTPROCESS_SUCCESS_REASON: Final[str] = "主回复已完成，后处理副作用已按降级容错策略执行"

PROMPT_VARIABLE_CURRENT_TIME: Final[str] = "CURRENT_TIME"
PROMPT_VARIABLE_CURRENT_MESSAGE: Final[str] = "CURRENT_MESSAGE"
PROMPT_VARIABLE_CORE_SUMMARY: Final[str] = "CORE_SUMMARY"
PROMPT_VARIABLE_KEY_FACTS: Final[str] = "KEY_FACTS"
PROMPT_VARIABLE_MEMORY_SNIPPETS: Final[str] = "MEMORY_SNIPPETS"
PROMPT_VARIABLE_LONG_TERM_MEMORY: Final[str] = "LONG_TERM_MEMORY"
PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: Final[str] = "EXTERNAL_KNOWLEDGE"
PROMPT_VARIABLE_USER_PROFILE: Final[str] = "USER_PROFILE"
PROMPT_VARIABLE_EMOTION_PRIMARY: Final[str] = "EMOTION_PRIMARY"
PROMPT_VARIABLE_EMOTION_INTENSITY: Final[str] = "EMOTION_INTENSITY"
PROMPT_VARIABLE_EMOTION_VALENCE: Final[str] = "EMOTION_VALENCE"
PROMPT_VARIABLE_EMOTION_AROUSAL: Final[str] = "EMOTION_AROUSAL"
PROMPT_VARIABLE_EMOTION_TRIGGER: Final[str] = "EMOTION_TRIGGER"

CHAT_STREAM_TYPE_REPLY_CHUNK: Final[str] = "reply_chunk"
CHAT_STREAM_TYPE_THOUGHT_CONTENT: Final[str] = "thought_content"
CHAT_STREAM_TYPE_EMOTION_UPDATE: Final[str] = "emotion_update"
CHAT_STREAM_GENERATION_ERROR: Final[str] = "generation_failed"
CHAT_STREAM_EMPTY_RESPONSE_ERROR: Final[str] = "Assistant returned empty content"

CHAT_WORKFLOW_REDIS_WRITE_OK: Final[str] = "redis_write_ok"
CHAT_WORKFLOW_REDIS_WRITE_SKIPPED: Final[str] = "redis_write_skipped"
CHAT_WORKFLOW_REDIS_WRITE_FAILED: Final[str] = "redis_write_failed"
CHAT_WORKFLOW_PG_WRITE_OK: Final[str] = "pg_write_ok"
CHAT_WORKFLOW_PG_WRITE_SKIPPED: Final[str] = "pg_write_skipped"
CHAT_WORKFLOW_PG_WRITE_FAILED: Final[str] = "pg_write_failed"
