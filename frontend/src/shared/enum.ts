/**
 * RAG 切片策略常量
 */
export const RAG_CHUNK_STRATEGY = {
  SLIDING_WINDOW: "sliding_window",
  STRUCTURED_AST: "structured_ast",
  SEMANTIC_PARENT_CHILD: "semantic_parent_child",
  REGEX: "regex"
} as const;

/**
 * RAG 来源类型常量
 */
export const RAG_SOURCE_TYPE = {
  LOCAL_FILE: "local_file",
  URL: "url"
} as const;

/**
 * RAG 文档状态常量
 */
export const RAG_DOCUMENT_STATUS = {
  INGESTING: "ingesting",
  PARSING: "parsing",
  EMBEDDING: "embedding",
  COMPLETED: "completed",
  FAILED: "failed",
  ACTIVE: "active",
  DEPRECATED: "deprecated"
} as const;

/**
 * RAG 检索路由常量
 */
export const RAG_RETRIEVAL_ROUTE = {
  SEARCH: "search",
  MODULAR: "modular",
  AGENTIC: "agentic"
} as const;

/**
 * RAG schema_version
 */
export const RAG_SCHEMA_VERSION = "rag.v1";

/**
 * 用户画像类别常量
 * 做什么：定义前端与 Python API 共享的用户画像类别。
 * 为什么这样做：避免组件、服务层和 Store 中出现魔法字符串。
 * 输入输出：无。
 * 边界条件：自定义类别必须配合 custom_category_name 使用。
 * 异常行为：无。
 */
export const USER_PROFILE_CATEGORY = {
  APPEARANCE: "appearance",
  PERSONALITY: "personality",
  LIKES: "likes",
  DISLIKES: "dislikes",
  FEARS: "fears",
  EXPECTATIONS: "expectations",
  HABITS: "habits",
  CUSTOM: "custom",
} as const;

/**
 * 用户画像来源类型常量
 * 做什么：定义画像来源，区分手动录入与模型整理。
 * 为什么这样做：来源标签和置信度展示必须与后端枚举一致。
 * 输入输出：无。
 * 边界条件：手动画像在 UI 中展示为已确认。
 * 异常行为：无。
 */
export const USER_PROFILE_SOURCE_TYPE = {
  MANUAL: "manual",
  MODEL_EXTRACTED: "model_extracted",
} as const;

/**
 * 用户画像条目状态常量
 * 做什么：定义画像条目的服务端生命周期状态。
 * 为什么这样做：前端默认只展示 active，但类型层仍需承载后端响应。
 * 输入输出：无。
 * 边界条件：deleted 与 superseded 不应在普通画像页面主动展示。
 * 异常行为：无。
 */
export const USER_PROFILE_STATUS = {
  ACTIVE: "active",
  SUPERSEDED: "superseded",
  DELETED: "deleted",
  REJECTED: "rejected",
} as const;

/**
 * 用户画像缓存状态常量
 * 做什么：定义 Redis 压缩缓存状态。
 * 为什么这样做：缓存状态条、重建按钮和轮询退出条件必须统一。
 * 输入输出：无。
 * 边界条件：rebuilding 需要轮询直到进入终态。
 * 异常行为：failed 状态需要展示 last_error。
 */
export const USER_PROFILE_CACHE_STATUS = {
  VALID: "valid",
  DIRTY: "dirty",
  MISSING: "missing",
  REBUILDING: "rebuilding",
  FAILED: "failed",
} as const;

/** 用户画像主协议版本。 */
export const USER_PROFILE_SCHEMA_VERSION = "user_profile.v1";

/** 用户画像缓存协议版本。 */
export const USER_PROFILE_CACHE_SCHEMA_VERSION = "user_profile.cache.v1";

/** 压缩审计协议版本。 */
export const COMPRESSION_AUDIT_SCHEMA_VERSION = "compression.audit.v1";

/** 压缩回放协议版本。 */
export const COMPRESSION_REPLAY_SCHEMA_VERSION = "compression.replay.v1";

/** 压缩事件协议版本。 */
export const COMPRESSION_EVENT_SCHEMA_VERSION = "compression.event.v1";

/**
 * 压缩阶段常量
 * 做什么：定义上下文压缩治理各阶段的跨层稳定枚举值。
 * 为什么这样做：压缩审计列表、回放详情和筛选器必须共用同一套值，禁止散落魔法字符串。
 * 输入输出：无。
 * 边界条件：新增后端阶段时必须同步补充中文标签。
 * 异常行为：无。
 */
export const COMPRESSION_STAGE = {
  MESSAGE_TRIM: "message_trim",
  SHORT_SUMMARY: "short_summary",
  LONG_SUMMARY: "long_summary",
  MEMORY_SLOT_VARIABLE: "memory_slot_variable",
  HISTORICAL_CONTEXT_MERGE: "historical_context_merge",
  HARD_TRUNCATION: "hard_truncation",
} as const;

/**
 * 压缩作用域常量
 * 做什么：定义上下文压缩动作可能作用的 Prompt 或记忆范围。
 * 为什么这样做：前端筛选与详情展示必须能覆盖当前后端真实返回的全部作用域。
 * 输入输出：无。
 * 边界条件：部分旧计划未列出的 memory_snippets/core_summary/key_facts 由后端实际枚举补齐。
 * 异常行为：无。
 */
export const COMPRESSION_SCOPE = {
  SESSION_HISTORY: "session_history",
  LONG_TERM_MEMORY: "long_term_memory",
  EXTERNAL_KNOWLEDGE: "external_knowledge",
  USER_PROFILE: "user_profile",
  MEMORY_SNIPPETS: "memory_snippets",
  CORE_SUMMARY: "core_summary",
  KEY_FACTS: "key_facts",
  MEMORY_SLOT: "memory_slot",
  HISTORICAL_CONTEXT: "historical_context",
} as const;

/**
 * 压缩触发原因常量
 * 做什么：定义触发压缩治理的稳定原因枚举。
 * 为什么这样做：列表筛选、详情说明和复制摘要都必须展示稳定中文文案。
 * 输入输出：无。
 * 边界条件：未知原因由服务层兜底为 final_prompt_token_over_limit。
 * 异常行为：无。
 */
export const COMPRESSION_TRIGGER_REASON = {
  REDIS_WINDOW_OVERFLOW: "redis_window_overflow",
  HISTORY_SESSION_ROLLOVER: "history_session_rollover",
  MEMORY_SLOT_TOKEN_OVER_LIMIT: "memory_slot_token_over_limit",
  SINGLE_VARIABLE_TOKEN_OVER_LIMIT: "single_variable_token_over_limit",
  FINAL_PROMPT_TOKEN_OVER_LIMIT: "final_prompt_token_over_limit",
} as const;

/**
 * 压缩状态常量
 * 做什么：定义后端真实落盘的压缩审计状态。
 * 为什么这样做：避免组件中直接书写 SUCCESS/FAILED/SKIPPED 字符串。
 * 输入输出：无。
 * 边界条件：前端"已降级/强制截断"属于派生展示态，不写入此常量。
 * 异常行为：无。
 */
export const COMPRESSION_STATUS = {
  SUCCESS: "SUCCESS",
  FAILED: "FAILED",
  SKIPPED: "SKIPPED",
} as const;

/**
 * 压缩审计动作类型常量
 * 做什么：定义当前写入 audit_logs.action_type 的压缩动作名称。
 * 为什么这样做：兼容后端专用接口未就绪时从通用审计日志中过滤压缩记录。
 * 输入输出：无。
 * 边界条件：必须与 Python COMPRESSION_AUDIT_ACTION_TYPE 保持一致。
 * 异常行为：无。
 */
export const COMPRESSION_AUDIT_ACTION_TYPE = "CONTEXT_COMPRESSION";

/** 压缩阶段中文标签。 */
export const COMPRESSION_STAGE_LABEL: Record<typeof COMPRESSION_STAGE[keyof typeof COMPRESSION_STAGE], string> = {
  [COMPRESSION_STAGE.MESSAGE_TRIM]: "消息裁剪",
  [COMPRESSION_STAGE.SHORT_SUMMARY]: "短摘要压缩",
  [COMPRESSION_STAGE.LONG_SUMMARY]: "长摘要压缩",
  [COMPRESSION_STAGE.MEMORY_SLOT_VARIABLE]: "变量压缩",
  [COMPRESSION_STAGE.HISTORICAL_CONTEXT_MERGE]: "统一历史背景",
  [COMPRESSION_STAGE.HARD_TRUNCATION]: "强制截断",
};

/** 压缩作用域中文标签。 */
export const COMPRESSION_SCOPE_LABEL: Record<typeof COMPRESSION_SCOPE[keyof typeof COMPRESSION_SCOPE], string> = {
  [COMPRESSION_SCOPE.SESSION_HISTORY]: "会话历史",
  [COMPRESSION_SCOPE.LONG_TERM_MEMORY]: "长期记忆",
  [COMPRESSION_SCOPE.EXTERNAL_KNOWLEDGE]: "外部知识",
  [COMPRESSION_SCOPE.USER_PROFILE]: "用户画像",
  [COMPRESSION_SCOPE.MEMORY_SNIPPETS]: "记忆片段",
  [COMPRESSION_SCOPE.CORE_SUMMARY]: "核心摘要",
  [COMPRESSION_SCOPE.KEY_FACTS]: "关键事实",
  [COMPRESSION_SCOPE.MEMORY_SLOT]: "记忆槽位",
  [COMPRESSION_SCOPE.HISTORICAL_CONTEXT]: "历史背景",
};

/** 压缩触发原因中文标签。 */
export const COMPRESSION_TRIGGER_REASON_LABEL: Record<typeof COMPRESSION_TRIGGER_REASON[keyof typeof COMPRESSION_TRIGGER_REASON], string> = {
  [COMPRESSION_TRIGGER_REASON.REDIS_WINDOW_OVERFLOW]: "短期窗口溢出",
  [COMPRESSION_TRIGGER_REASON.HISTORY_SESSION_ROLLOVER]: "历史会话滚动",
  [COMPRESSION_TRIGGER_REASON.MEMORY_SLOT_TOKEN_OVER_LIMIT]: "记忆槽位超限",
  [COMPRESSION_TRIGGER_REASON.SINGLE_VARIABLE_TOKEN_OVER_LIMIT]: "单变量超限",
  [COMPRESSION_TRIGGER_REASON.FINAL_PROMPT_TOKEN_OVER_LIMIT]: "最终 Prompt 超限",
};

/** 压缩状态中文标签。 */
export const COMPRESSION_STATUS_LABEL: Record<string, string> = {
  [COMPRESSION_STATUS.SUCCESS]: "成功",
  [COMPRESSION_STATUS.FAILED]: "失败",
  [COMPRESSION_STATUS.SKIPPED]: "已跳过",
  DEGRADED: "已降级",
  HARD_TRUNCATED: "强制截断",
};

/**
 * Chat Workflow schema_version 常量。
 * 做什么：定义 Phase 8.5 聊天主链路节点化事件协议版本。
 * 为什么这样做：跨层通信必须版本化，禁止在组件和服务层散落魔法字符串。
 * 输入输出：无。
 * 边界条件：后端升级协议版本时必须同步更新前端解析层与测试。
 * 异常行为：无。
 */
export const CHAT_WORKFLOW_SCHEMA_VERSION = {
  CHAT_WORKFLOW_V1: 'chat.workflow.v1',
} as const;

/**
 * Chat 模式常量。
 * 做什么：定义当前前后端共享的聊天模式标识。
 * 为什么这样做：Plan 投影视图、调试事件和消息元数据都需要稳定模式枚举。
 * 输入输出：无。
 * 边界条件：Phase 8.5 仅支持 daily_chat。
 * 异常行为：无。
 */
export const CHAT_MODE = {
  DAILY_CHAT: 'daily_chat',
} as const;

/**
 * Chat Plan 预设常量。
 * 做什么：定义当前聊天主链路使用的单一预设计划标识。
 * 为什么这样做：前端需要区分普通闲聊计划与未来 Phase 9 可能出现的更多计划。
 * 输入输出：无。
 * 边界条件：当前仅允许 daily_chat.default.v1。
 * 异常行为：无。
 */
export const CHAT_PLAN_PRESET = {
  DAILY_CHAT_DEFAULT: 'daily_chat.default.v1',
} as const;

/**
 * Chat Workflow 节点类型常量。
 * 做什么：定义日常闲聊主链路中所有可观测节点的稳定枚举值。
 * 为什么这样做：SSE 事件消费、Store 状态更新和 UI 展示必须共用同一套节点标识。
 * 输入输出：无。
 * 边界条件：新增节点时必须同步补充中文标签与状态映射。
 * 异常行为：无。
 */
export const CHAT_WORKFLOW_NODE_TYPE = {
  MESSAGE_INGRESS: 'message_ingress',
  INPUT_RECONSTRUCTION: 'input_reconstruction',
  SESSION_CONTEXT_LOAD: 'session_context_load',
  LONG_TERM_MEMORY_RAG: 'long_term_memory_rag',
  USER_PROFILE_INJECTION: 'user_profile_injection',
  KNOWLEDGE_RAG: 'knowledge_rag',
  CONTEXT_GOVERNANCE: 'context_governance',
  PROMPT_ASSEMBLY: 'prompt_assembly',
  MAIN_CHAT_LLM: 'main_chat_llm',
  RESPONSE_PERSISTENCE: 'response_persistence',
  LONG_TERM_MEMORY_COMPRESSION: 'long_term_memory_compression',
  USER_PROFILE_EXTRACTION: 'user_profile_extraction',
  POSTPROCESS_COMMIT: 'postprocess_commit',
  ERROR_RECOVERY: 'error_recovery',
  FINALIZE: 'finalize',
} as const;

/**
 * Chat 节点状态常量。
 * 做什么：定义前后端共享的节点运行状态。
 * 为什么这样做：条件未进入、降级继续和真实失败必须被显式区分，避免错误语义混淆。
 * 输入输出：无。
 * 边界条件：NOT_ENTERED_BY_CONDITION 属于正常条件路由结果，绝不能当作错误处理。
 * 异常行为：无。
 */
export const CHAT_NODE_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
  DEGRADED: 'degraded',
  NOT_ENTERED_BY_CONDITION: 'not_entered_by_condition',
} as const;

/**
 * Chat Workflow 事件类型常量。
 * 做什么：定义 Phase 8.5 聊天工作流会通过 SSE 推送的事件类型。
 * 为什么这样做：SSEManager 与调试面板必须集中依赖统一事件枚举，避免条件分支散落字符串。
 * 输入输出：无。
 * 边界条件：过渡期仍需兼容既有 CHAT_STREAM。
 * 异常行为：无。
 */
export const CHAT_WORKFLOW_EVENT_TYPE = {
  EVT_CHAT_PLAN_STARTED: 'EVT_CHAT_PLAN_STARTED',
  EVT_CHAT_NODE_STARTED: 'EVT_CHAT_NODE_STARTED',
  EVT_CHAT_NODE_COMPLETED: 'EVT_CHAT_NODE_COMPLETED',
  EVT_CHAT_NODE_FAILED: 'EVT_CHAT_NODE_FAILED',
  EVT_CHAT_NODE_DEGRADED: 'EVT_CHAT_NODE_DEGRADED',
  EVT_CHAT_CONDITION_EVALUATED: 'EVT_CHAT_CONDITION_EVALUATED',
  EVT_CHAT_STREAM_CHUNK: 'EVT_CHAT_STREAM_CHUNK',
  EVT_CHAT_POSTPROCESS_STARTED: 'EVT_CHAT_POSTPROCESS_STARTED',
  EVT_CHAT_POSTPROCESS_COMPLETED: 'EVT_CHAT_POSTPROCESS_COMPLETED',
  EVT_CHAT_PLAN_COMPLETED: 'EVT_CHAT_PLAN_COMPLETED',
} as const;

/** Chat Workflow 节点中文标签。 */
export const CHAT_WORKFLOW_NODE_LABEL: Record<
  typeof CHAT_WORKFLOW_NODE_TYPE[keyof typeof CHAT_WORKFLOW_NODE_TYPE],
  string
> = {
  [CHAT_WORKFLOW_NODE_TYPE.MESSAGE_INGRESS]: '接收用户输入',
  [CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION]: '输入重构',
  [CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD]: '会话上下文加载',
  [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG]: '长期记忆检索',
  [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION]: '用户画像注入',
  [CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG]: '知识库检索',
  [CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE]: '上下文治理',
  [CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY]: 'Prompt 装配',
  [CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM]: '主对话生成',
  [CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE]: '回复持久化',
  [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_COMPRESSION]: '长期记忆压缩',
  [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_EXTRACTION]: '用户画像提取',
  [CHAT_WORKFLOW_NODE_TYPE.POSTPROCESS_COMMIT]: '后处理提交',
  [CHAT_WORKFLOW_NODE_TYPE.ERROR_RECOVERY]: '错误恢复',
  [CHAT_WORKFLOW_NODE_TYPE.FINALIZE]: '流程收尾',
};

/** Chat 节点状态中文标签。 */
export const CHAT_NODE_STATUS_LABEL: Record<
  typeof CHAT_NODE_STATUS[keyof typeof CHAT_NODE_STATUS],
  string
> = {
  [CHAT_NODE_STATUS.PENDING]: '等待中',
  [CHAT_NODE_STATUS.RUNNING]: '进行中',
  [CHAT_NODE_STATUS.SUCCEEDED]: '已完成',
  [CHAT_NODE_STATUS.FAILED]: '失败',
  [CHAT_NODE_STATUS.DEGRADED]: '已降级',
  [CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION]: '条件未进入',
};

/**
 * 全局统一的错误码枚举
 * 做什么：定义前后端统一的错误码常量。
 * 为什么这样做：避免代码中出现魔法数字，统一错误处理逻辑。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export enum ErrorCode {
  SUCCESS = 0,

  // 系统级错误 (1000-1999)
  SYSTEM_ERROR = 1000,
  CONFIG_LOAD_FAILED = 1001,
  DB_CONNECT_FAILED = 1002,

  // 业务逻辑错误 (2000-2999)
  BUSINESS_ERROR = 2000,
  STATE_INVALID = 2001,
  PERMISSION_DENIED = 2002,

  // 外部依赖错误 (3000-3999)
  EXTERNAL_ERROR = 3000,
  LLM_CALL_FAILED = 3001,
  TOOL_EXECUTE_FAILED = 3002,
}

/**
 * WebSocket 消息类型常量
 * 做什么：定义前后端统一的 WebSocket 消息类型常量。
 * 为什么这样做：避免代码中出现魔法字符串，统一消息类型处理逻辑。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export const WS_MSG_TYPE = {
  // 基础消息类型
  PING: "PING",
  PONG: "PONG",
  CHAT_STREAM: "CHAT_STREAM",
  ERROR: "ERROR",
  // 前端发送的命令类型 (CMD_*)
  CMD_SYNC_INIT_STATE: "CMD_SYNC_INIT_STATE",
  CMD_USER_INPUT: "CMD_USER_INPUT",
  CMD_AUTH_RESPONSE: "CMD_AUTH_RESPONSE",
  CMD_CANCEL_TASK: "CMD_CANCEL_TASK",
  CMD_SWITCH_SESSION: "CMD_SWITCH_SESSION",
  // Go 推送的事件类型 (EVT_*)
  EVT_INIT_STATE: "EVT_INIT_STATE",
  EVT_PLAN_SNAPSHOT: "EVT_PLAN_SNAPSHOT",
  EVT_NODE_STATUS_UPDATE: "EVT_NODE_STATUS_UPDATE",
  EVT_MEMORY_UPDATED: "EVT_MEMORY_UPDATED",
  EVT_DEBUG_LOG: "EVT_DEBUG_LOG",
  EVT_CHAT_STREAM_CHUNK: "EVT_CHAT_STREAM_CHUNK",
  EVT_CHAT_PLAN_STARTED: "EVT_CHAT_PLAN_STARTED",
  EVT_CHAT_NODE_STARTED: "EVT_CHAT_NODE_STARTED",
  EVT_CHAT_NODE_COMPLETED: "EVT_CHAT_NODE_COMPLETED",
  EVT_CHAT_NODE_FAILED: "EVT_CHAT_NODE_FAILED",
  EVT_CHAT_NODE_DEGRADED: "EVT_CHAT_NODE_DEGRADED",
  EVT_CHAT_CONDITION_EVALUATED: "EVT_CHAT_CONDITION_EVALUATED",
  EVT_CHAT_POSTPROCESS_STARTED: "EVT_CHAT_POSTPROCESS_STARTED",
  EVT_CHAT_POSTPROCESS_COMPLETED: "EVT_CHAT_POSTPROCESS_COMPLETED",
  EVT_CHAT_PLAN_COMPLETED: "EVT_CHAT_PLAN_COMPLETED",
  // 流式渲染事件类型 —— 参考 streaming_rendering_plan.md §3.1
  EVT_EMOTION_UPDATE: "EVT_EMOTION_UPDATE",
  EVT_REPLY_CHUNK: "EVT_REPLY_CHUNK",

  // RAG SSE 事件
  EVT_RAG_THOUGHT: "EVT_RAG_THOUGHT",
  EVT_RAG_CITATION: "EVT_RAG_CITATION",

  // === Phase 4 新增：可观测性相关 ===
  // Go -> Electron: 链路 Span 数据（启用诊断面板时推送）
  EVT_TELEMETRY_TRACE: "EVT_TELEMETRY_TRACE",
  // Go -> Electron: 监控指标数据点（启用诊断面板时每秒推送）
  EVT_TELEMETRY_METRICS: "EVT_TELEMETRY_METRICS",
  // Electron -> Go: 启用/禁用实时追踪推送
  CMD_SET_TELEMETRY_MODE: "CMD_SET_TELEMETRY_MODE",

  // === 聊天记录展示功能新增 ===
  REQ_GET_CALENDAR_METADATA: "REQ_GET_CALENDAR_METADATA",
  RES_CALENDAR_METADATA: "RES_CALENDAR_METADATA",
  REQ_GET_CHAT_HISTORY: "REQ_GET_CHAT_HISTORY",
  RES_CHAT_HISTORY: "RES_CHAT_HISTORY",

  // === Chat 状态通知事件（来自 ChatStatusPublisher） ===
  EVT_CHAT_STATUS: "EVT_CHAT_STATUS",
} as const;

/**
 * WebSocket 消息类型联合类型
 */
export type WSMsgType = typeof WS_MSG_TYPE[keyof typeof WS_MSG_TYPE];

/**
 * 健康检查状态常量
 * 做什么：定义前后端统一的健康检查状态常量。
 * 为什么这样做：避免代码中出现魔法字符串，统一健康状态处理逻辑。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export const HEALTH_STATUS = {
  HEALTHY: "healthy",
  UNHEALTHY: "unhealthy",
  DEGRADED: "degraded",
} as const;

/**
 * 标准 JSON 响应结构
 * 做什么：定义前后端统一的 API 响应数据结构。
 * 为什么这样做：规范化接口返回格式，方便前端统一拦截和处理。
 * 输入输出：泛型 T 代表 data 字段的具体类型。
 * 边界条件：无。
 * 异常行为：无。
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface ResponseModel<T = any> {
  code: ErrorCode;
  msg: string;
  data: T;
  trace_id: string;
}
