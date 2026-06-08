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


class UserProfileCategory(str, Enum):
    """用户画像类别枚举。"""

    APPEARANCE = "appearance"
    PERSONALITY = "personality"
    LIKES = "likes"
    DISLIKES = "dislikes"
    FEARS = "fears"
    EXPECTATIONS = "expectations"
    HABITS = "habits"
    CUSTOM = "custom"


class UserProfileSourceType(str, Enum):
    """用户画像来源类型枚举。"""

    MANUAL = "manual"
    MODEL_EXTRACTED = "model_extracted"


class UserProfileStatus(str, Enum):
    """用户画像状态枚举。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    REJECTED = "rejected"


class UserProfileCacheStatus(str, Enum):
    """用户画像压缩缓存状态枚举。"""

    VALID = "valid"
    DIRTY = "dirty"
    MISSING = "missing"
    REBUILDING = "rebuilding"
    FAILED = "failed"


class UserProfileSourceRefType(str, Enum):
    """用户画像来源引用类型枚举。"""

    MANUAL_INPUT = "manual_input"
    INTERACTION = "interaction"
    SESSION_COMPRESSION = "session_compression"
    LONG_SUMMARY = "long_summary"


class UserProfileMutationAction(str, Enum):
    """用户画像变更动作枚举。"""

    ADD = "add"
    CONFIRM_EXISTING = "confirm_existing"
    SUPERSEDE = "supersede"
    REJECT = "reject"


class UserProfileConflictType(str, Enum):
    """用户画像冲突类型枚举。"""

    SEMANTIC_CONFLICT = "semantic_conflict"


class UserProfileConflictResolution(str, Enum):
    """用户画像冲突解决策略枚举。"""

    SUPERSEDE = "supersede"


USER_PROFILE_SCHEMA_VERSION = "user_profile.v1"
USER_PROFILE_EXTRACT_SCHEMA_VERSION = "user_profile.extract.v1"
USER_PROFILE_MUTATION_SCHEMA_VERSION = "user_profile.mutation.v1"
USER_PROFILE_CACHE_SCHEMA_VERSION = "user_profile.cache.v1"
USER_PROFILE_DEFAULT_USER_ID = "local_default_user"
USER_PROFILE_AUTO_COMMIT_CONFIDENCE_THRESHOLD = 0.75
# 用户画像摘要模型单次请求超时秒数。
# 做什么：限制后台摘要模型调用的单次等待时间，避免 OpenAI 客户端连接阶段长时间阻塞。
# 为什么这样做：用户画像摘要是辅助上下文，但小模型在本地或代理链路较慢时需要足够时间生成压缩结果。
USER_PROFILE_SUMMARY_MODEL_TIMEOUT_SECONDS = 60.0
# 用户画像摘要后台重建任务总超时秒数。
# 做什么：限制摘要重建任务从获取锁到写入缓存的整体生命周期。
# 为什么这样做：外层任务超时必须大于模型单次请求超时，避免模型还没到 60 秒就被后台任务提前取消。
USER_PROFILE_SUMMARY_REBUILD_TASK_TIMEOUT_SECONDS = 75.0
# 用户画像摘要最大字符数。
# 做什么：限制写入 Redis 并注入 Prompt 的画像摘要长度。
# 为什么这样做：防止画像条目过多导致 Prompt 上下文被辅助信息挤占。
USER_PROFILE_SUMMARY_MAX_LENGTH = 2000
# 用户画像本地兜底摘要最多拼接的条目数量。
# 做什么：模型不可用时只选取前若干条 active 画像生成确定性摘要。
# 为什么这样做：保证兜底摘要可控、可读，并避免 Redis 缓存与 Prompt 过长。
USER_PROFILE_SUMMARY_FALLBACK_MAX_ITEMS = 40

USER_PROFILE_CHANGE_REASON_MANUAL_CREATE = "手动新增用户画像"
USER_PROFILE_CHANGE_REASON_MANUAL_UPDATE_SNAPSHOT = "手动编辑前快照"
USER_PROFILE_CHANGE_REASON_MANUAL_DELETE_SNAPSHOT = "手动删除前快照"
USER_PROFILE_CHANGE_REASON_MODEL_ADD = "模型提取新增用户画像"
USER_PROFILE_CHANGE_REASON_MODEL_SUPERSEDE_OLD = "模型提取冲突覆盖前快照"
USER_PROFILE_CHANGE_REASON_MODEL_SUPERSEDE_NEW = "模型提取冲突覆盖新增画像"
USER_PROFILE_REASON_DUPLICATE_CONFIRM = "新候选与已有画像重复，更新最近确认时间"
USER_PROFILE_REASON_ADD = "新画像"

USER_PROFILE_CATEGORY_LABELS = {
    UserProfileCategory.APPEARANCE.value: "外貌",
    UserProfileCategory.PERSONALITY.value: "性格",
    UserProfileCategory.LIKES.value: "喜欢的东西",
    UserProfileCategory.DISLIKES.value: "厌恶的东西",
    UserProfileCategory.FEARS.value: "害怕的东西",
    UserProfileCategory.EXPECTATIONS.value: "期待的东西",
    UserProfileCategory.HABITS.value: "癖好",
    UserProfileCategory.CUSTOM.value: "自定义",
}

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
