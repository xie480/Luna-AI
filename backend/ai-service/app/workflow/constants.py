"""Phase 8.5 workflow 常量定义。"""

from __future__ import annotations

from enum import Enum
from typing import Final


class ChatWorkflowSchemaVersion(str, Enum):
    """Workflow 协议版本。"""

    CHAT_WORKFLOW_V1 = "chat.workflow.v1"


class ChatMode(str, Enum):
    """当前支持的聊天模式。"""

    DAILY_CHAT = "daily_chat"
    CASUAL_CHAT = "casual_chat"


class ChatPlanPreset(str, Enum):
    """当前启用的内置预设图。"""

    DAILY_CHAT_DEFAULT = "daily_chat.default.v1"
    CASUAL_CHAT_DEFAULT = "casual_chat.default.v1"


class ChatWorkflowNodeType(str, Enum):
    """当前主图真实使用的节点类型。"""

    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    LONG_TERM_MEMORY_RAG = "long_term_memory_rag"
    USER_PROFILE_INJECTION = "user_profile_injection"
    KNOWLEDGE_RAG = "knowledge_rag"
    CONTEXT_GOVERNANCE = "context_governance"
    PROMPT_ASSEMBLY = "prompt_assembly"
    MAIN_CHAT_LLM = "main_chat_llm"
    RESPONSE_PERSISTENCE = "response_persistence"
    FINALIZE = "finalize"
    # --- Phase 12（v3.0）新增：MCP Skill 执行节点 ---
    MCP_SKILL_EXECUTION = "mcp_skill_execution"
    # --- Phase 12（v3.0）新增：MCP 前置判断节点 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"


class ChatNodeStatus(str, Enum):
    """节点运行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"
    NOT_ENTERED_BY_CONDITION = "not_entered_by_condition"


class ChatConditionalRoute(str, Enum):
    """条件边结果。"""

    ENTER_LONG_TERM_MEMORY_RAG = "enter_long_term_memory_rag"
    BYPASS_LONG_TERM_MEMORY_RAG = "bypass_long_term_memory_rag"
    ENTER_KNOWLEDGE_RAG = "enter_knowledge_rag"
    BYPASS_KNOWLEDGE_RAG = "bypass_knowledge_rag"
    # --- Phase 12（v3.0）新增：Skill 路由 ---
    ENTER_MCP_SKILL = "enter_mcp_skill"
    BYPASS_MCP_SKILL = "bypass_mcp_skill"
    # --- Phase 12（v3.0）新增：MCP 前置判断路由 ---
    ENTER_MCP_SKILL_FROM_JUDGE = "enter_mcp_skill_from_judge"
    BYPASS_MCP_SKILL_FROM_JUDGE = "bypass_mcp_skill_from_judge"
    ENTER_MCP_INTENT_JUDGE = "enter_mcp_intent_judge"
    BYPASS_MCP_INTENT_JUDGE = "bypass_mcp_intent_judge"


class ChatWorkflowEventType(str, Enum):
    """当前真实发送的事件类型。"""

    EVT_CHAT_PLAN_STARTED = "EVT_CHAT_PLAN_STARTED"
    EVT_CHAT_NODE_STARTED = "EVT_CHAT_NODE_STARTED"
    EVT_CHAT_NODE_COMPLETED = "EVT_CHAT_NODE_COMPLETED"
    EVT_CHAT_NODE_FAILED = "EVT_CHAT_NODE_FAILED"
    EVT_CHAT_NODE_DEGRADED = "EVT_CHAT_NODE_DEGRADED"
    EVT_CHAT_CONDITION_EVALUATED = "EVT_CHAT_CONDITION_EVALUATED"
    EVT_CHAT_PLAN_COMPLETED = "EVT_CHAT_PLAN_COMPLETED"


class ChatWorkflowErrorCode(str, Enum):
    """当前真实使用的错误码。"""

    PROMPT_ASSEMBLY_FAILED = "CHAT_WORKFLOW_PROMPT_ASSEMBLY_FAILED"
    MAIN_LLM_FAILED = "CHAT_WORKFLOW_MAIN_LLM_FAILED"
    NODE_UNEXPECTED_FAILED = "CHAT_WORKFLOW_NODE_UNEXPECTED_FAILED"


class ChatWorkflowGraphNodeName(str, Enum):
    """LangGraph 内部节点名。"""

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
    FINALIZE = "finalize"
    # --- Phase 12（v3.0）新增：Skill 节点 ---
    MCP_SKILL_EXECUTION = "mcp_skill_execution"
    MCP_SKILL_BYPASS = "mcp_skill_bypass"
    # --- Phase 12（v3.0）新增：MCP 前置判断节点 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"
    MCP_INTENT_BYPASS = "mcp_intent_bypass"


CHAT_WORKFLOW_CHECKPOINT_TABLE: Final[str] = "langgraph_chat_checkpoints"
CHAT_WORKFLOW_CHECKPOINT_NS_SEPARATOR: Final[str] = ":"
CHAT_WORKFLOW_DEFAULT_LOCALE: Final[str] = "zh-CN"
CHAT_WORKFLOW_DEFAULT_TIMEZONE: Final[str] = "Asia/Shanghai"
CHAT_WORKFLOW_DEFAULT_USER_ID: Final[str] = "local_default_user"
CHAT_WORKFLOW_CONTEXT_WINDOW_READY: Final[str] = "ready"
CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED: Final[str] = "degraded"
CHAT_WORKFLOW_EMPTY_PROFILE_REASON: Final[str] = "用户画像为空"
CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON: Final[str] = "未触发长期记忆检索"
CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON: Final[str] = "未触发知识库检索"
CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON: Final[str] = "输入重构降级"

class ChatMCPAgentPhase(str, Enum):
    """MCP Agent 执行阶段枚举。

    做什么：标识 MCPSkillExecutionNode 中三 Agent 协作的当前执行阶段。
    为什么这样做：使用枚举替代硬编码的字符串常量，避免拼写错误和散落。
    """
    IDLE = "idle"
    SKILL_SCREENING = "skill_screening"
    SKILL_LOADING = "skill_loading"
    SKILL_EXECUTION = "skill_execution"
    SKILL_FALLBACK = "skill_fallback"
    SKILL_FINAL_FAIL = "skill_final_fail"

# Phase 12（v3.0）新增：Skill 常量
CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON: Final[str] = "未触发 MCP Skill 调用"
CHAT_WORKFLOW_SKILL_DEGRADED_REASON: Final[str] = "MCP Skill 执行降级"
CHAT_WORKFLOW_SKILL_NO_SKILL_REASON: Final[str] = "MCP Agent 判定无需调用技能"

# Phase 12 新增：MCP 工具输出变量名，用于下游 Prompt 装配时引用。
PROMPT_VARIABLE_MCP_TOOL_OUTPUT: Final[str] = "MCP_TOOL_OUTPUT"

# Phase 12（v3.1）新增：Skill 执行结果摘要变量名，用于向 chat/memory.j2 注入 LLM 压缩后的技能执行摘要。
PROMPT_VARIABLE_SKILL_EXECUTION_SUMMARY: Final[str] = "SKILL_EXECUTION_SUMMARY"

PROMPT_VARIABLE_CURRENT_TIME: Final[str] = "CURRENT_TIME"
PROMPT_VARIABLE_CURRENT_MESSAGE: Final[str] = "CURRENT_MESSAGE"
PROMPT_VARIABLE_CORE_SUMMARY: Final[str] = "CORE_SUMMARY"
PROMPT_VARIABLE_KEY_FACTS: Final[str] = "KEY_FACTS"
PROMPT_VARIABLE_MEMORY_SNIPPETS: Final[str] = "MEMORY_SNIPPETS"
PROMPT_VARIABLE_KNOWLEDGE_DOCS: Final[str] = "KNOWLEDGE_DOCS"
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
# 非流式统一响应事件类型
CHAT_STREAM_TYPE_UNIFIED_RESPONSE: Final[str] = "unified_response"
CHAT_STREAM_GENERATION_ERROR: Final[str] = "generation_failed"
CHAT_STREAM_EMPTY_RESPONSE_ERROR: Final[str] = "Assistant returned empty content"

CHAT_WORKFLOW_REDIS_WRITE_OK: Final[str] = "redis_write_ok"
CHAT_WORKFLOW_REDIS_WRITE_SKIPPED: Final[str] = "redis_write_skipped"
CHAT_WORKFLOW_REDIS_WRITE_FAILED: Final[str] = "redis_write_failed"
CHAT_WORKFLOW_PG_WRITE_OK: Final[str] = "pg_write_ok"
CHAT_WORKFLOW_PG_WRITE_SKIPPED: Final[str] = "pg_write_skipped"
CHAT_WORKFLOW_PG_WRITE_FAILED: Final[str] = "pg_write_failed"
