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
 * 边界条件：Phase 2 增强后支持 daily_chat（深度日常助理）与 casual_chat（极速轻松闲聊）。
 * 异常行为：无。
 */
export const CHAT_MODE = {
  /**
   * 深度日常助理模式：完整工作流、RAG、记忆写入。
   */
  DAILY_CHAT: 'daily_chat',
  /**
   * 极速闲聊模式：跳过 RAG 与记忆写入，仅保留基础对话能力，响应更快。
   */
  CASUAL_CHAT: 'casual_chat',
  /**
   * 智能规划模式：Phase 9 Plan-State-Node DAG 工作流，拆解为多个执行阶段深度完成任务。
   */
  PLAN_STATE_NODE: 'plan_state_node',
  /**
   * 万能循环模式：Agent Loop 架构，Goal-Stable / Plan-Mutable 的 6 层循环。
   */
  AGENT_LOOP: 'agent_loop',
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
  /** Phase 12 新增：MCP 工具执行节点。 */
  MCP_TOOL_EXECUTION: 'mcp_tool_execution',
  /** Phase 12 新增：MCP 意图判断节点。 */
  MCP_INTENT_JUDGE: 'mcp_intent_judge',
  /** Phase 12 新增：MCP 技能执行节点（原 mcp_tool_execution 升级）。 */
  MCP_SKILL_EXECUTION: 'mcp_skill_execution',
  /** Agent Loop 新增：简化输入重构节点（代词消歧，不做路由决策）。 */
  INPUT_RECONSTRUCTION_SIMPLIFIED: 'input_reconstruction_simplified',
  /** Agent Loop 新增：Agent Loop DAG 引擎节点（GoalLock -> GlobalPlanner -> StepLoop -> FinalVerify）。 */
  DAG_ENGINE_AGENT_LOOP: 'dag_engine_agent_loop',
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
  [CHAT_WORKFLOW_NODE_TYPE.MESSAGE_INGRESS]: '终端信号截获',
  [CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION]: '指令流解构重塑',
  [CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD]: '潜意识链路挂载',
  [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG]: '深层神经元寻址',
  [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION]: '人格矩阵印入',
  [CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG]: '全息图谱扫描',
  [CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE]: '信息流降噪清洗',
  [CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY]: '认知协议封装',
  [CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM]: '核心算力推演',
  [CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE]: '记忆快照固化',
  [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_COMPRESSION]: '潜意识降维折叠',
  [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_EXTRACTION]: '行为特征提取',
  [CHAT_WORKFLOW_NODE_TYPE.POSTPROCESS_COMMIT]: '逻辑链收束锁定',
  [CHAT_WORKFLOW_NODE_TYPE.ERROR_RECOVERY]: '混沌态熔断自愈',
  [CHAT_WORKFLOW_NODE_TYPE.FINALIZE]: '资源链路静默',
  [CHAT_WORKFLOW_NODE_TYPE.MCP_TOOL_EXECUTION]: '外挂义体接管',
  [CHAT_WORKFLOW_NODE_TYPE.MCP_INTENT_JUDGE]: '外挂义体权限校验',
  [CHAT_WORKFLOW_NODE_TYPE.MCP_SKILL_EXECUTION]: '外挂义体驱动接管',
  [CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION_SIMPLIFIED]: '轻量指令解构',
  [CHAT_WORKFLOW_NODE_TYPE.DAG_ENGINE_AGENT_LOOP]: '万能循环引擎',
};

/** Chat 节点状态中文标签。 */
export const CHAT_NODE_STATUS_LABEL: Record<
  typeof CHAT_NODE_STATUS[keyof typeof CHAT_NODE_STATUS],
  string
> = {
  [CHAT_NODE_STATUS.PENDING]: '就绪挂起',
  [CHAT_NODE_STATUS.RUNNING]: '高速演算中',
  [CHAT_NODE_STATUS.SUCCEEDED]: '态势收敛',
  [CHAT_NODE_STATUS.FAILED]: '逻辑崩塌',
  [CHAT_NODE_STATUS.DEGRADED]: '受损降级',
  [CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION]: '路由旁路',
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

  // === Phase 13：权限治理与前端 Gating 事件（Python AI Service -> Electron） ===
  // Python -> Electron: 推送高危工具鉴权挂起事件，要求用户确认
  EVT_TOOL_AUTH_REQUIRED: "EVT_TOOL_AUTH_REQUIRED",
  // Electron -> Python: 用户对挂起鉴权请求的审批响应（同意/拒绝）
  CMD_TOOL_AUTH_RESPONSE: "CMD_TOOL_AUTH_RESPONSE",
  // Electron -> Python: 重连后请求同步当前所有 PENDING_APPROVAL 状态的鉴权请求
  CMD_SYNC_PENDING_AUTHS: "CMD_SYNC_PENDING_AUTHS",
  // Python -> Electron: 同步当前所有有效的 PENDING_APPROVAL 列表
  EVT_PENDING_AUTHS_SYNC: "EVT_PENDING_AUTHS_SYNC",

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

/**
 * MCP 市场分类常量。
 * 做什么：定义 MCP 市场支持的分类枚举。
 */
export const MCP_MARKET_CATEGORY = {
  ALL: 'all',
  DEVELOPER_TOOLS: 'developer_tools',
  DATA_ACCESS: 'data_access',
  COMMUNICATION: 'communication',
  PRODUCTIVITY: 'productivity',
  AI_AND_ML: 'ai_and_ml',
  SYSTEM: 'system',
  UTILITY: 'utility',
  UNCATEGORIZED: 'uncategorized',
} as const;

/**
 * MCP 市场分类中文标签。
 */
export const MCP_MARKET_CATEGORY_LABEL: Record<string, string> = {
  [MCP_MARKET_CATEGORY.ALL]: '全部分类',
  [MCP_MARKET_CATEGORY.DEVELOPER_TOOLS]: '开发者工具',
  [MCP_MARKET_CATEGORY.DATA_ACCESS]: '数据访问',
  [MCP_MARKET_CATEGORY.COMMUNICATION]: '通信与通知',
  [MCP_MARKET_CATEGORY.PRODUCTIVITY]: '效率工具',
  [MCP_MARKET_CATEGORY.AI_AND_ML]: 'AI 与机器学习',
  [MCP_MARKET_CATEGORY.SYSTEM]: '系统工具',
  [MCP_MARKET_CATEGORY.UTILITY]: '通用工具',
  [MCP_MARKET_CATEGORY.UNCATEGORIZED]: '未分类',
};

/**
 * MCP 健康状态常量。
 */
export const MCP_HEALTH_STATUS = {
  ONLINE: 'online',
  OFFLINE: 'offline',
  UNKNOWN: 'unknown',
  BUILTIN: 'builtin',
} as const;

/**
 * MCP 健康状态中文标签。
 */
export const MCP_HEALTH_STATUS_LABEL: Record<string, string> = {
  [MCP_HEALTH_STATUS.ONLINE]: '在线',
  [MCP_HEALTH_STATUS.OFFLINE]: '离线',
  [MCP_HEALTH_STATUS.UNKNOWN]: '未知',
  [MCP_HEALTH_STATUS.BUILTIN]: '内置',
};

/**
 * MCP 工具来源常量。
 * 做什么：定义 MCP 工具的来源类型。
 */
export const MCP_TOOL_SOURCE = {
  LOCAL: 'local',
  REMOTE: 'remote',
} as const;

/**
 * MCP 工具来源中文标签。
 */
export const MCP_TOOL_SOURCE_LABEL: Record<string, string> = {
  [MCP_TOOL_SOURCE.LOCAL]: '系统内置',
  [MCP_TOOL_SOURCE.REMOTE]: '远程接入',
};

/**
 * MCP 服务器来源常量。
 * 做什么：区分 MCP 服务器的来源类型。
 * 为什么这样做：面板展示需要区分"本地注册"和"远程接入"。
 */
export const MCP_SERVER_SOURCE = {
  LOCAL: 'local',
  REMOTE: 'remote',
  MARKET: 'market',
} as const;

export type MCPServerSource = typeof MCP_SERVER_SOURCE[keyof typeof MCP_SERVER_SOURCE];

/**
 * MCP 本地服务器注册模式常量。
 */
export const MCP_LOCAL_REGISTER_MODE = {
  MANUAL: 'manual',
  JSON_IMPORT: 'json_import',
} as const;

export type MCPLocalRegisterMode = typeof MCP_LOCAL_REGISTER_MODE[keyof typeof MCP_LOCAL_REGISTER_MODE];

/**
 * MCP 鉴权类型常量。
 */
export const MCP_AUTH_TYPE = {
  NONE: 'none',
  BEARER: 'bearer',
  API_KEY: 'api_key',
  BASIC: 'basic',
} as const;

/**
 * MCP 鉴权类型中文标签。
 */
export const MCP_AUTH_TYPE_LABEL: Record<string, string> = {
  [MCP_AUTH_TYPE.NONE]: '无需鉴权',
  [MCP_AUTH_TYPE.BEARER]: 'Bearer Token',
  [MCP_AUTH_TYPE.API_KEY]: 'API Key',
  [MCP_AUTH_TYPE.BASIC]: '用户名密码',
};

/**
 * TTS 语言选项常量。
 * 做什么：定义 TTS 语音合成的语言选项。
 * 为什么这样做：前端设置面板和后端 Prompt 模板需要共享同一个语言枚举。
 * 输入输出：无。
 * 边界条件：zh 为默认中文模式，ja 为日语模式。
 * 异常行为：无。
 */
export const TTS_LANGUAGE = {
  /** 中文（默认） */
  ZH: 'zh',
  /** 日语 */
  JA: 'ja',
} as const;

/** TTS 语言选项中文标签。 */
export const TTS_LANGUAGE_LABEL: Record<string, string> = {
  [TTS_LANGUAGE.ZH]: '中文',
  [TTS_LANGUAGE.JA]: '日语',
};

// ============================================================
// Phase 9：DAG 工作流枚举常量
// ============================================================

/**
 * DAG 原子节点类型常量。
 * 做什么：定义 Phase 9 State 内部 Step 中可使用的 5 种原子节点类型。
 * 为什么这样做：与后端 DagNodeType 枚举保持一致，前端标签映射与状态着色依赖此枚举。
 * 输入输出：无。
 * 边界条件：新增节点类型时必须同步补充中文标签映射。
 * 异常行为：无。
 */
export const DAG_NODE_TYPE = {
  RESOURCE_LOADING: 'resource_loading',
  TOOL_EXECUTE: 'tool_execute',
  DATA_TRANSFORM: 'data_transform',
  LONG_TERM_MEMORY: 'long_term_memory',
  KNOWLEDGE_RAG: 'knowledge_rag',
} as const;

/**
 * DAG 节点类型联合类型。
 * 做什么：从 DAG_NODE_TYPE 常量对象中提取类型。
 * 为什么这样做：确保类型定义与共享常量保持一致。
 */
export type DagNodeType = typeof DAG_NODE_TYPE[keyof typeof DAG_NODE_TYPE];

/**
 * DAG 节点类型中文标签映射。
 * 做什么：将 DAG_NODE_TYPE 枚举映射为前端可展示的中文标签。
 * 为什么这样做：AtomicNode 卡片标题、搜索匹配标签都依赖此映射。
 */
export const DAG_NODE_TYPE_LABEL: Record<DagNodeType, string> = {
  [DAG_NODE_TYPE.RESOURCE_LOADING]: '资源加载',
  [DAG_NODE_TYPE.TOOL_EXECUTE]: '工具执行',
  [DAG_NODE_TYPE.DATA_TRANSFORM]: '数据转换',
  [DAG_NODE_TYPE.LONG_TERM_MEMORY]: '长期记忆',
  [DAG_NODE_TYPE.KNOWLEDGE_RAG]: '知识检索',
};

/**
 * DAG 节点状态常量。
 * 做什么：定义 Plan/State/Step/Node 各层级共享的状态枚举。
 * 为什么这样做：前端状态着色、动画和交互逻辑全部依赖此枚举。
 * 输入输出：无。
 * 边界条件：PENDING_USER_APPROVAL 为 Gating 审批态，需特殊 UI 处理。
 * 异常行为：无。
 */
export const DAG_NODE_STATUS = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  SUCCEEDED: 'SUCCEEDED',
  DEGRADED: 'DEGRADED',
  FAILED: 'FAILED',
  SKIPPED: 'SKIPPED',
  PENDING_USER_APPROVAL: 'PENDING_USER_APPROVAL',
} as const;

/**
 * DAG 节点状态联合类型。
 */
export type DagNodeStatus = typeof DAG_NODE_STATUS[keyof typeof DAG_NODE_STATUS];

/**
 * DAG 节点状态中文标签映射。
 * 做什么：将 DAG_NODE_STATUS 枚举映射为前端可展示的中文标签。
 * 为什么这样做：节点卡片状态标识、时间线状态显示依赖此映射。
 */
export const DAG_NODE_STATUS_LABEL: Record<DagNodeStatus, string> = {
  [DAG_NODE_STATUS.PENDING]: '等待中',
  [DAG_NODE_STATUS.RUNNING]: '执行中',
  [DAG_NODE_STATUS.SUCCEEDED]: '已完成',
  [DAG_NODE_STATUS.DEGRADED]: '已降级',
  [DAG_NODE_STATUS.FAILED]: '失败',
  [DAG_NODE_STATUS.SKIPPED]: '已跳过',
  [DAG_NODE_STATUS.PENDING_USER_APPROVAL]: '等待审批',
};

/**
 * Phase 9 DAG 工作流 SSE 事件类型常量。
 * 做什么：定义前端需要监听的 12 种 DAG 事件。
 * 为什么这样做：SSEManager 注册监听和事件分发依赖稳定枚举，避免散落魔法字符串。
 * 输入输出：无。
 * 边界条件：新增事件类型时必须同步补充 SSEManager 注册与 Store 处理方法。
 * 异常行为：无。
 */
export const DAG_WORKFLOW_EVENT_TYPE = {
  PLAN_CREATED: 'EVT_DAG_PLAN_CREATED',
  STATE_STARTED: 'EVT_DAG_STATE_STARTED',
  SKILL_SCREENING: 'EVT_DAG_SKILL_SCREENING',
  STEP_PLAN_GENERATED: 'EVT_DAG_STEP_PLAN_GENERATED',
  NODE_STARTED: 'EVT_DAG_NODE_STARTED',
  NODE_COMPLETED: 'EVT_DAG_NODE_COMPLETED',
  NODE_GATING: 'EVT_DAG_NODE_GATING',
  STATE_EVALUATED: 'EVT_DAG_STATE_EVALUATED',
  PLAN_REPLANNED: 'EVT_DAG_PLAN_REPLANNED',
  PLAN_COMPLETED: 'EVT_DAG_PLAN_COMPLETED',
  PLAN_TERMINATED: 'EVT_DAG_PLAN_TERMINATED',
  BUDGET_EXHAUSTED: 'EVT_DAG_BUDGET_EXHAUSTED',
  // Agent Loop 新增事件
  GOAL_LOCKED: 'EVT_DAG_GOAL_LOCKED',
  STEP_THINKING: 'EVT_DAG_STEP_THINKING',
  STEP_OBSERVED: 'EVT_DAG_STEP_OBSERVED',
  STEP_EVALUATED: 'EVT_DAG_STEP_EVALUATED',
  STEP_REPAIRED: 'EVT_DAG_STEP_REPAIRED',
  FINAL_VERIFIED: 'EVT_DAG_FINAL_VERIFIED',
} as const;

/**
 * DAG 工作流事件类型联合类型。
 */
export type DagWorkflowEventType = typeof DAG_WORKFLOW_EVENT_TYPE[keyof typeof DAG_WORKFLOW_EVENT_TYPE];
