from enum import Enum

class ModelSize(str, Enum):
    LARGE = "large"
    MEDIUM = "medium"
    SMALL = "small"

class Role(str, Enum):
    """全局统一的角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# 已知不支持 OpenAI 原生 json_schema response_format 的供应商关键字。
# 做什么：供 LLMClient 在请求前识别供应商能力，避免 DeepSeek 等兼容接口返回 400。
# 为什么这样做：结构化输出能力属于供应商差异，不应散落在 Agent 业务逻辑中硬编码。
LLM_STRUCTURED_OUTPUT_UNSUPPORTED_PROVIDER_KEYWORDS = ("deepseek",)

# WebSocket 消息类型常量
WS_MSG_TYPE_PING = "PING"
WS_MSG_TYPE_PONG = "PONG"
WS_MSG_TYPE_CHAT_STREAM = "CHAT_STREAM"
WS_MSG_TYPE_ERROR = "ERROR"
WS_MSG_TYPE_CMD_SYNC_INIT_STATE = "CMD_SYNC_INIT_STATE"
WS_MSG_TYPE_CMD_USER_INPUT = "CMD_USER_INPUT"
WS_MSG_TYPE_EVT_INIT_STATE = "EVT_INIT_STATE"
WS_MSG_TYPE_REQ_GET_CALENDAR_METADATA = "REQ_GET_CALENDAR_METADATA"
WS_MSG_TYPE_RES_CALENDAR_METADATA = "RES_CALENDAR_METADATA"
WS_MSG_TYPE_REQ_GET_CHAT_HISTORY = "REQ_GET_CHAT_HISTORY"
WS_MSG_TYPE_RES_CHAT_HISTORY = "RES_CHAT_HISTORY"
WS_MSG_TYPE_EVT_MEMORY_SYNC = "EVT_MEMORY_SYNC"

# 健康检查状态常量
HEALTH_STATUS_HEALTHY = "healthy"
HEALTH_STATUS_UNHEALTHY = "unhealthy"
HEALTH_STATUS_DEGRADED = "degraded"

class PrimaryIntent(str, Enum):
    MODIFY_PLAN = "MODIFY_PLAN"
    GREETING = "GREETING"
    QUERY_INFO = "QUERY_INFO"
    EMOTION_VENTING = "EMOTION_VENTING"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"
    TOOL_INVOCATION = "TOOL_INVOCATION"

class IntentCategory(str, Enum):
    TASK_MANAGEMENT = "TASK_MANAGEMENT"
    CHAT = "CHAT"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    EMOTION_SUPPORT = "EMOTION_SUPPORT"

class DagRouteHint(str, Enum):
    MULTI_SOURCE_RETRIEVAL_WORKFLOW = "MULTI_SOURCE_RETRIEVAL_WORKFLOW"
    FAST_CHAT = "FAST_CHAT"
    AGENTIC_WORKFLOW = "AGENTIC_WORKFLOW"
    GATING_APPROVAL = "GATING_APPROVAL"

class RetrievalType(str, Enum):
    LONG_TERM_MEMORY = "LONG_TERM_MEMORY"
    EXTERNAL_KNOWLEDGE = "EXTERNAL_KNOWLEDGE"
    EXPERIENCE_REFLECTION = "EXPERIENCE_REFLECTION"


RAG_SCHEMA_VERSION = "rag.v1"
RAG_QDRANT_COLLECTION = "luna_rag_index"
RAG_EVENT_THOUGHT = "EVT_RAG_THOUGHT"
RAG_EVENT_CITATION = "EVT_RAG_CITATION"
RAG_DEFAULT_VECTOR_SIZE = 768


class MemoryChunkType(str, Enum):
    SUMMARY = "SUMMARY"
    FACT = "FACT"


class RagSourceType(str, Enum):
    """RAG 知识来源类型枚举"""

    LOCAL_FILE = "local_file"
    URL = "url"


class RagDocumentStatus(str, Enum):
    """RAG 文档摄入状态枚举"""

    PARSING = "parsing"
    EMBEDDING = "embedding"
    ACTIVE = "active"
    FAILED = "failed"
    DEPRECATED = "deprecated"


class RagChunkStrategy(str, Enum):
    """RAG 切片策略枚举"""

    SLIDING_WINDOW = "sliding_window"
    STRUCTURED_AST = "structured_ast"
    SEMANTIC_PARENT_CHILD = "semantic_parent_child"
    REGEX = "regex"


class RagRetrievalRoute(str, Enum):
    """RAG 检索路由枚举"""

    KEYWORD = "keyword"
    HYBRID = "hybrid"
    AGENTIC = "agentic"
