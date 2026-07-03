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
WS_MSG_TYPE_EVT_LONG_ANSWER_CREATED = "EVT_LONG_ANSWER_CREATED"
WS_MSG_TYPE_EVT_LONG_ANSWER_CHUNK = "EVT_LONG_ANSWER_CHUNK"
WS_MSG_TYPE_EVT_LONG_ANSWER_STATUS = "EVT_LONG_ANSWER_STATUS"
WS_MSG_TYPE_EVT_LONG_ANSWER_COMPLETED = "EVT_LONG_ANSWER_COMPLETED"
WS_MSG_TYPE_EVT_LONG_ANSWER_FAILED = "EVT_LONG_ANSWER_FAILED"
LONG_ANSWER_SCHEMA_VERSION = "long_answer.v1"

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
WS_MSG_TYPE_EVT_CHAT_STATUS = "EVT_CHAT_STATUS"
CHAT_STATUS_SCHEMA_VERSION = "chat_status.v1"

# Phase 13 Gating 权限治理消息类型常量
WS_MSG_TYPE_EVT_TOOL_AUTH_REQUIRED = "EVT_TOOL_AUTH_REQUIRED"
WS_MSG_TYPE_CMD_TOOL_AUTH_RESPONSE = "CMD_TOOL_AUTH_RESPONSE"
WS_MSG_TYPE_CMD_SYNC_GATING_STATE = "CMD_SYNC_GATING_STATE"
WS_MSG_TYPE_EVT_GATING_STATE = "EVT_GATING_STATE"
GATING_SCHEMA_VERSION = "gating.v1"

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


class LongAnswerStatus(str, Enum):
    """长回答状态枚举。"""

    PENDING = "PENDING"
    GENERATING = "GENERATING"
    SUMMARY_GENERATING = "SUMMARY_GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERABLE_FAILED = "RECOVERABLE_FAILED"


class AnswerMode(str, Enum):
    """回答模式枚举。"""

    SHORT = "short"
    LONG = "long"


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
USER_PROFILE_SUMMARY_MODEL_TIMEOUT_SECONDS = 60.0
USER_PROFILE_SUMMARY_REBUILD_TASK_TIMEOUT_SECONDS = 75.0
USER_PROFILE_SUMMARY_MAX_LENGTH = 2000
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

COMPRESSION_AUDIT_ACTION_TYPE = "CONTEXT_COMPRESSION"
COMPRESSION_AUDIT_SCHEMA_VERSION = "compression.audit.v1"
COMPRESSION_REPLAY_SCHEMA_VERSION = "compression.replay.v1"
COMPRESSION_EVENT_SCHEMA_VERSION = "compression.event.v1"
COMPRESSION_SPAN_NAME = "ContextCompression"
COMPRESSION_SPAN_SERVICE = "python_ai"
COMPRESSION_STATUS_SUCCESS = "SUCCESS"
COMPRESSION_STATUS_FAILED = "FAILED"
COMPRESSION_STATUS_SKIPPED = "SKIPPED"
COMPRESSION_EVENT_TRIGGERED = "COMPRESSION_TRIGGERED"
COMPRESSION_EVENT_INPUT_MEASURED = "COMPRESSION_INPUT_MEASURED"
COMPRESSION_EVENT_EXECUTED = "COMPRESSION_EXECUTED"
COMPRESSION_EVENT_OUTPUT_MEASURED = "COMPRESSION_OUTPUT_MEASURED"
COMPRESSION_EVENT_APPLIED = "COMPRESSION_APPLIED"
COMPRESSION_EVENT_COMPLETED = "COMPRESSION_COMPLETED"
COMPRESSION_EVENT_FAILED = "COMPRESSION_FAILED"
COMPRESSION_VARIABLE_HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"


class CompressionStage(str, Enum):
    """上下文压缩阶段枚举。"""

    MESSAGE_TRIM = "message_trim"
    SHORT_SUMMARY = "short_summary"
    LONG_SUMMARY = "long_summary"
    MEMORY_SLOT_VARIABLE = "memory_slot_variable"
    HISTORICAL_CONTEXT_MERGE = "historical_context_merge"
    HARD_TRUNCATION = "hard_truncation"


class CompressionTriggerReason(str, Enum):
    """上下文压缩触发原因枚举。"""

    REDIS_WINDOW_OVERFLOW = "redis_window_overflow"
    HISTORY_SESSION_ROLLOVER = "history_session_rollover"
    MEMORY_SLOT_TOKEN_OVER_LIMIT = "memory_slot_token_over_limit"
    SINGLE_VARIABLE_TOKEN_OVER_LIMIT = "single_variable_token_over_limit"
    FINAL_PROMPT_TOKEN_OVER_LIMIT = "final_prompt_token_over_limit"


class CompressionScope(str, Enum):
    """上下文压缩作用域枚举。"""

    SESSION_HISTORY = "session_history"
    LONG_TERM_MEMORY = "long_term_memory"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    USER_PROFILE = "user_profile"
    MEMORY_SNIPPETS = "memory_snippets"
    CORE_SUMMARY = "core_summary"
    KEY_FACTS = "key_facts"
    MEMORY_SLOT = "memory_slot"
    HISTORICAL_CONTEXT = "historical_context"


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


# ============================================================
# EVT_CHAT_STATUS — SSE Chat 状态通知协议常量
# ============================================================
# 做什么：定义 Chat 主链路 SSE 状态推送的事件类型、Schema 版本以及阶段/状态枚举。
# 为什么这样做：前端需要区分"理解中"、"检索中"、"流式输出中"等不同阶段，并且后端
#              必须按 node 粒度精准推送状态，而不是由前端靠猜测渲染。所有枚举值和
#              常量在此集中管理，避免事件名、枚举值散落在业务代码中出现不一致。
# 边界条件：ChatStatusStage 和 ChatStatusState 均为 str Enum，保证与 SSE 外层
#           JSON 序列化时直接产出可读字符串，无需二次映射。


class ChatStatusStage(str, Enum):
    """Chat 主链路阶段枚举，对应 DAG 图中的各个 node 执行阶段。

    每个阶段都对应一个具体的 Workflow Node，由 Node 内部的 ChatStatusPublisher
    在 Node 执行入口和出口触发。前端根据 stage 判断当前正在执行什么类型的操作，
    从而展示对应的拟人化状态文本。

    以下为 DAG 完整执行顺序所对应的所有阶段：
      1. INPUT_RECONSTRUCTION    — 输入重构与意图理解
      2. SESSION_CONTEXT_LOAD    — 会话上下文加载（Redis 窗口）
      3. RAG_RETRIEVAL           — 长期记忆检索
      4. KNOWLEDGE_RAG           — 知识库检索
      5. USER_PROFILE_INJECTION  — 用户画像注入
      6. CONTEXT_GOVERNANCE      — 上下文治理与压缩
      7. CHAT_PROMPT_ASSEMBLY    — 最终 Chat Prompt 装配
      8. LLM_STREAMING           — 主模型流式生成
      9. RESPONSE_PERSISTENCE    — 回复持久化落盘
     10. FINALIZE                — 结束归档
    """
    INPUT_RECONSTRUCTION = "input_reconstruction"
    SESSION_CONTEXT_LOAD = "session_context_load"
    RAG_RETRIEVAL = "rag_retrieval"
    KNOWLEDGE_RAG = "knowledge_rag"
    USER_PROFILE_INJECTION = "user_profile_injection"
    CONTEXT_GOVERNANCE = "context_governance"
    CHAT_PROMPT_ASSEMBLY = "chat_prompt_assembly"
    LLM_STREAMING = "llm_streaming"
    RESPONSE_PERSISTENCE = "response_persistence"
    FINALIZE = "finalize"
    # --- Phase 12（v3.0）新增：Skill 执行阶段 ---
    MCP_SKILL_EXECUTION = "mcp_skill_execution"
    # --- Phase 12（v3.0）新增：MCP Skill 子阶段（用于 display_text 细化） ---
    MCP_SKILL_SCREENING = "mcp_skill_screening"
    MCP_SKILL_LOADING = "mcp_skill_loading"
    MCP_SKILL_RESOURCE_LOADING = "mcp_skill_resource_loading"
    MCP_SKILL_TOOL_EXECUTING = "mcp_skill_tool_executing"
    MCP_SKILL_FALLBACK = "mcp_skill_fallback"
    MCP_SKILL_EVALUATING = "mcp_skill_evaluating"
    MCP_SKILL_MEMORY_EXTRACTING = "mcp_skill_memory_extracting"
    # --- Phase 12（v3.0）新增：MCP 前置判断阶段 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"
    # --- Phase 13（v3.1）新增：MCP Skill 执行结果摘要阶段 ---
    MCP_SKILL_SUMMARY = "mcp_skill_summary"
    # --- LLM 调用频率限制等待阶段 ---
    LLM_RATE_LIMIT_WAIT = "llm_rate_limit_wait"
    # --- 非流式统一响应模式新增阶段 ---
    LLM_CALLING = "llm_calling"             # 新增：正在调用 LLM（非流式，等待完整回复）
    LLM_PARSING = "llm_parsing"             # 新增：正在解析 LLM 结构化输出（提取 thought/emotion/reply）
    TTS_SYNTHESIZING = "tts_synthesizing"   # 新增：正在合成 TTS 完整音频
    FINAL_RESPONSE = "final_response"       # 新增：正在组装并发送最终响应包

    # --- Phase 9 新增：State 循环外的引擎节点阶段 ---
    DAG_ENGINE_ENTRY = "dag_engine_entry"                   # DAG 引擎入口
    DAG_PLAN_GENERATION = "dag_plan_generation"             # 全局 Plan 生成
    DAG_STATE_EXECUTION = "dag_state_execution"             # State 执行器
    DAG_STATE_EVALUATION = "dag_state_evaluation"           # State 评估
    DAG_PLAN_REPLAN = "dag_plan_replan"                     # Plan 重构
    DAG_PLAN_SUMMARY = "dag_plan_summary"                   # Plan 结果汇总
    DAG_RESULT_COMPRESSION = "dag_result_compression"       # 结果压缩

    # --- Phase 9 新增：State 循环内的执行节点阶段 ---
    DAG_SKILL_SCREENING = "dag_skill_screening"             # Skill 初筛
    DAG_STEP_PLAN_GENERATION = "dag_step_plan_generation"   # Step Plan 生成
    DAG_STEP_EXECUTION = "dag_step_execution"               # Step 执行
    DAG_STEP_MERGE = "dag_step_merge"                       # Step 合并
    DAG_RESOURCE_LOADING = "dag_resource_loading"           # 资源加载
    DAG_TOOL_EXECUTE = "dag_tool_execute"                   # 工具执行
    DAG_DATA_TRANSFORM = "dag_data_transform"               # 数据转换

    # --- Agent Loop 专用阶段（Phase 9 Agent Loop 重构新增） ---
    DAG_AGENT_STEP_THINK = "dag_agent_step_think"                     # Agent 步骤思考
    DAG_AGENT_OBSERVE = "dag_agent_observe"                           # Agent 观察执行结果
    DAG_AGENT_STEP_REPAIR = "dag_agent_step_repair"                   # Agent 步骤修复重试
    DAG_AGENT_STEP_FAST_PASS = "dag_agent_step_fast_pass"             # Agent 纯思考快速通过


class ChatStatusState(str, Enum):
    """Chat 主链路状态枚举，标识当前阶段的执行状态。

    每个 node 至少会触发 RUNNING 和 COMPLETED 两个状态。异常场景下
    会触发 ERROR 或 SKIPPED。CANCELLED 由取消接口触发。
    """
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error"
    CANCELLED = "cancelled"
