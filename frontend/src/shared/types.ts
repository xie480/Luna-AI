import {
  CHAT_MODE,
  CHAT_NODE_STATUS,
  CHAT_PLAN_PRESET,
  CHAT_WORKFLOW_EVENT_TYPE,
  CHAT_WORKFLOW_NODE_TYPE,
  CHAT_WORKFLOW_SCHEMA_VERSION,
  DAG_NODE_STATUS,
  DAG_NODE_TYPE,
  DAG_WORKFLOW_EVENT_TYPE,
  WS_MSG_TYPE,
} from './enum';

/**
 * WebSocket 消息类型枚举值类型。
 * 做什么：从 [`WS_MSG_TYPE`](frontend/src/shared/enum.ts) 常量对象中提取类型。
 * 为什么这样做：确保类型定义与共享常量保持一致，避免手写联合类型漂移。
 * 输入输出：无。
 * 边界条件：新增消息类型后会自动纳入联合类型。
 * 异常行为：无。
 */
export type WSMsgType = typeof WS_MSG_TYPE[keyof typeof WS_MSG_TYPE];

/**
 * Chat Workflow 节点类型。
 * 做什么：描述 Phase 8.5 聊天主链路允许出现的节点枚举值。
 * 为什么这样做：SSE 事件、Store 投影与 UI 标签映射都必须依赖同一套强类型节点标识。
 * 输入输出：无。
 * 边界条件：节点新增时必须同步补充常量与展示映射。
 * 异常行为：无。
 */
export type ChatWorkflowNodeType = typeof CHAT_WORKFLOW_NODE_TYPE[keyof typeof CHAT_WORKFLOW_NODE_TYPE];

/**
 * Chat 节点状态。
 * 做什么：描述后端投影到前端的节点运行状态。
 * 为什么这样做：条件未进入、降级继续和真实失败必须用不同类型显式区分。
 * 输入输出：无。
 * 边界条件：[`CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION`](frontend/src/shared/enum.ts) 属于正常路由结果。
 * 异常行为：无。
 */
export type ChatNodeStatus = typeof CHAT_NODE_STATUS[keyof typeof CHAT_NODE_STATUS];

/**
 * Chat Workflow 事件类型。
 * 做什么：描述 Phase 8.5 通过 SSE 推送的计划、节点、条件、后处理事件。
 * 为什么这样做：前端需要用强类型分发而不是自由字符串。
 * 输入输出：无。
 * 边界条件：过渡期仍需兼容既有 [`WS_MSG_TYPE.CHAT_STREAM`](frontend/src/shared/enum.ts) 事件。
 * 异常行为：无。
 */
export type ChatWorkflowEventType = typeof CHAT_WORKFLOW_EVENT_TYPE[keyof typeof CHAT_WORKFLOW_EVENT_TYPE];

/**
 * Chat 模式类型。
 * 做什么：描述当前聊天模式枚举。
 * 为什么这样做：Plan 投影视图、消息元数据和输入框模式切换都需要持有模式信息。
 * 输入输出：无。
 * 边界条件：Phase 2 增强后支持 [`CHAT_MODE.DAILY_CHAT`](frontend/src/shared/enum.ts)（深度日常助理）
 *           与 [`CHAT_MODE.CASUAL_CHAT`](frontend/src/shared/enum.ts)（极速闲聊）。
 * 异常行为：无。
 */
export type ChatMode = typeof CHAT_MODE[keyof typeof CHAT_MODE];

/**
 * Chat Plan 预设类型。
 * 做什么：描述当前闲聊计划预设枚举。
 * 为什么这样做：为未来 Phase 9 多 Plan 扩展保留类型边界。
 * 输入输出：无。
 * 边界条件：当前仅支持 [`CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT`](frontend/src/shared/enum.ts)。
 * 异常行为：无。
 */
export type ChatPlanPreset = typeof CHAT_PLAN_PRESET[keyof typeof CHAT_PLAN_PRESET];

/**
 * WebSocket 消息结构。
 * 做什么：定义前后端统一的 WebSocket/SSE 兼容消息壳。
 * 为什么这样做：当前 SSEManager 会把 SSE 事件映射为旧的 WSMessage 结构统一消费。
 * 输入输出：泛型 `T` 代表 payload 字段的具体类型。
 * 边界条件：payload 可能为未知对象，调用方必须显式缩小类型。
 * 异常行为：无。
 */
export interface WSMessage<T = unknown> {
  type: WSMsgType;
  trace_id: string;
  payload: T;
}

/**
 * Ping 消息 Payload。
 * 做什么：定义 Ping 消息的数据结构。
 * 为什么这样做：规范化连接探测消息格式。
 * 输入输出：输入输出均为毫秒级时间戳。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface PingPayload {
  timestamp: number;
}

/**
 * Pong 消息 Payload。
 * 做什么：定义 Pong 消息的数据结构。
 * 为什么这样做：前端需要区分响应来源并更新 AI 服务连通性。
 * 输入输出：输出响应时间与来源标识。
 * 边界条件：source 由后端决定，前端只消费不推断。
 * 异常行为：无。
 */
export interface PongPayload {
  timestamp: number;
  source: string;
}

/**
 * Error 消息 Payload。
 * 做什么：定义错误消息的数据结构。
 * 为什么这样做：统一系统错误展示与日志记录入口。
 * 输入输出：输出错误码与错误文案。
 * 边界条件：message 可能来自不同后端模块，前端不可依赖固定文本做业务判断。
 * 异常行为：无。
 */
export interface ErrorPayload {
  code: number;
  message: string;
}

/**
 * ChatMessage 定义单条对话消息，用于多轮对话历史记录。
 * 做什么：定义前端维护历史记录和发送给后端的最小消息结构。
 * 为什么这样做：确保前端发送给后端的 history 格式与后端期望一致。
 * 输入输出：role 为对话角色，content 为消息正文。
 * 边界条件：role 只能是 `user`、`assistant` 或 `system`。
 * 异常行为：调用方必须在提交前保证 content 非空。
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * ChatRequest 消息 Payload。
 * 做什么：定义发送聊天请求时的载荷结构。
 * 为什么这样做：支持多轮对话，让模型感知历史上下文。
 * 输入输出：message 为当前输入，history 为按时间正序排列的历史记录。
 * 边界条件：history 为空数组时表示首次对话。
 * 异常行为：无。
 */
export interface ChatRequestPayload {
  message: string;
  history?: ChatMessage[];
}

/**
 * Chat 引用投影。
 * 做什么：承载主 Chat LLM 最终附带的引用信息。
 * 为什么这样做：assistant 元数据面板和引用展示需要稳定的前端结构。
 * 输入输出：字段来自后端 [`ChatStreamChunkPayload`](backend/ai-service/app/workflow/events.py) 的 `citations`。
 * 边界条件：citation_id 在不同后端实现中可能为 number 或 string，前端统一按联合类型承载。
 * 异常行为：无。
 */
export interface ChatCitationProjection {
  citation_id?: number | string;
  document_id?: string;
  document_name?: string;
  chunk_id?: string;
  content?: string;
  score?: number;
  source_type?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Phase 8.5 增强后的流式回复事件载荷。
 * 做什么：兼容既有 [`WS_MSG_TYPE.CHAT_STREAM`](frontend/src/shared/enum.ts) 的同时承载 interaction、节点与引用元数据。
 * 为什么这样做：保持现有流式气泡渲染体验，同时为 workflow 元数据接入提供结构化来源。
 * 输入输出：chunk 为当前文本块，`is_finished` 与 `is_final_chunk` 用于终态识别。
 * 边界条件：过渡期旧后端可能只下发旧字段，前端必须兼容缺失的新字段。
 * 异常行为：error 非空时表示该轮生成失败或终态异常。
 */
export interface ChatStreamPayload {
  type: string;
  chunk: string;
  is_finished: boolean;
  node_id: string;
  error?: string;
  schema_version?: typeof CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1;
  interaction_id?: string;
  assistant_message_id?: string;
  plan_preset_id?: typeof CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT;
  current_node_type?: typeof CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM;
  citations?: ChatCitationProjection[];
  is_final_chunk?: boolean;
  audio_uri?: string;
  is_sentence_chunk?: boolean;
}

/**
 * 非流式统一响应载荷 —— 对应后端 [`ChatUnifiedResponsePayload`](backend/ai-service/app/workflow/events.py)。
 * 做什么：承载后端非流式一次合成的完整回复包，包括回复文本、内心独白、
 *         情绪标记、已合成 TTS 音频地址及端到端耗时等元数据。
 * 为什么这样做：替代原有多段流式 SSE 推送，前端收到后一次完成语义切分、
 *             气泡队列编排、TTS 播放与 Live2D 表情同步。
 * 输入输出：由后端 [`publish_unified_response()`](backend/ai-service/app/workflow/nodes/helpers.py) 推送，
 *           前端 [`unifiedResponseHandler`](frontend/src/renderer/services/unifiedResponseHandler.ts) 消费。
 * 边界条件：
 *   - reply_text 可能为空（模型无有效回复）。
 *   - thought_text 为空时前端不展示内心独白。
 *   - audio_uri 为 null 时跳过 TTS 播放，前端降级为纯文本模式。
 *   - error 非空时表示整个统一响应生成失败。
 * 异常行为：无。
 */
export interface ChatUnifiedResponsePayload {
  /** SSE 事件类型标识，固定为 "unified_response"。 */
  type: 'unified_response';
  /** 模型完整回复文本，无流式拆分。 */
  reply_text: string;
  /** 模型内心独白 / 思维链文本（可选）。 */
  thought_text: string;
  /** 本轮回复对应的情绪标记（如 neutral / happy / sad）。 */
  emotion: string;
  /** 已合成 TTS 音频文件路径或 null（TTS 失败/禁用时）。 */
  audio_uri: string | null;
  /** 是否为本轮回复的终态包（统一响应始终为 true）。 */
  is_finished: boolean;
  /** 协议版本号。 */
  schema_version: string;
  /** 本轮交互 ID。 */
  interaction_id: string;
  /** assistant 消息 ID。 */
  assistant_message_id: string;
  /** 完成原因（stop / length / error）。 */
  finish_reason: string;
  /** 端到端生成耗时（毫秒），从 LLM 调用开始到前端可渲染。 */
  e2e_latency_ms: number;
  /** 引用列表。 */
  citations: ChatCitationProjection[];
  /** 错误信息，空字符串表示无错误。 */
  error: string;
  /**
   * 是否跳过前端持久化（聊天记录、近期记忆的存储）。
   * 为 true 时表示此回复仅用于气泡渲染、TTS 音频播放和 Live2D emotion 渲染，
   * 不加入聊天历史记录和近期记忆。
   */
  skip_persistence: boolean;
}

/**
 * 情绪更新事件 Payload —— 对应 [`WS_MSG_TYPE.EVT_EMOTION_UPDATE`](frontend/src/shared/enum.ts)。
 * 做什么：承载后端推送的 Live2D 情绪名称。
 * 为什么这样做：与流式渲染协议保持一致。
 * 输入输出：emotion 为情绪名称。
 * 边界条件：非法情绪会在消费层降级为 `neutral`。
 * 异常行为：无。
 */
export interface EmotionUpdatePayload {
  emotion: string;
}

/**
 * 回复文本块事件 Payload —— 对应 [`WS_MSG_TYPE.EVT_REPLY_CHUNK`](frontend/src/shared/enum.ts)。
 * 做什么：承载后端按标点断句后的完整句子文本块。
 * 为什么这样做：前端不再自行拆句，直接按语义完整短句渲染气泡。
 * 输入输出：chunk 为文本块，is_finished 标识是否结束。
 * 边界条件：空 chunk 不应触发气泡渲染。
 * 异常行为：无。
 */
export interface ReplyChunkPayload {
  chunk: string;
  is_finished: boolean;
}

/**
 * 单轮问答结构，用于近期记忆展示。
 * 做什么：定义前端展示的单轮问答数据结构。
 * 为什么这样做：用于 UI 快速回顾最近对话。
 * 输入输出：msgId 为唯一标识，timestamp 为秒级时间戳。
 * 边界条件：assistantContent 允许为空字符串表示异常终态。
 * 异常行为：无。
 */
export interface InteractionQA {
  msgId: string;
  userContent: string;
  assistantContent: string;
  timestamp: number;
}

/**
 * 初始状态同步事件 Payload —— 对应 [`WS_MSG_TYPE.EVT_INIT_STATE`](frontend/src/shared/enum.ts)。
 * 做什么：承载后端下发的当前会话初始状态，包括近期记忆等。
 * 为什么这样做：用于前端刷新或重启后恢复 UI 上下文。
 * 输入输出：sessionId 为当前会话，recentQA 为最近 3 轮问答。
 * 边界条件：recentQA 可能为空数组。
 * 异常行为：无。
 */
export interface InitStatePayload {
  sessionId: string;
  recentQA: InteractionQA[];
}

/**
 * Chat Workflow 统一事件信封。
 * 做什么：描述 Phase 8.5 节点化 SSE 事件的公共头信息。
 * 为什么这样做：SSEManager 需要在进入 Store 前完成基础字段校验与分发。
 * 输入输出：`payload` 为对应事件的强类型业务载荷。
 * 边界条件：`nodeType` 对计划级事件可为空。
 * 异常行为：无。
 */
export interface ChatWorkflowEventEnvelope<TPayload> {
  schemaVersion: typeof CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1;
  eventId: string;
  eventType: ChatWorkflowEventType;
  traceId: string;
  interactionId: string;
  sessionId: string;
  planPresetId: typeof CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT;
  nodeType?: ChatWorkflowNodeType;
  timestampMs: number;
  payload: TPayload;
}

/**
 * Chat Plan 开始/完成事件载荷。
 * 做什么：描述单轮闲聊计划的摘要性信息。
 * 为什么这样做：Phase 8.5 不展示完整 DAG，但仍需要识别本轮回复归属的计划与消息。
 * 输入输出：当前载荷包含节点观测数量和 assistant 消息 ID。
 * 边界条件：计划开始时 `nodeObservationCount` 通常为 0。
 * 异常行为：无。
 */
export interface ChatPlanLifecyclePayload {
  nodeObservationCount: number;
  assistantMessageId: string;
}

/**
 * 条件边评估载荷。
 * 做什么：描述条件节点是否进入及后端给出的原因。
 * 为什么这样做：前端必须展示"条件已评估 / 未进入原因"，而不是自行推导是否跳过。
 * 输入输出：sourceNodeType 为源节点，targetNodeType 为被判断节点。
 * 边界条件：reason 始终由后端提供，前端只能展示不能自造业务判断。
 * 异常行为：无。
 */
export interface ChatConditionEvaluatedPayload {
  sourceNodeType: ChatWorkflowNodeType;
  targetNodeType: ChatWorkflowNodeType;
  conditionEntered: boolean;
  routeName: string;
  reason: string;
  longTermMemoryReason?: string;
  knowledgeRagReason?: string;
  userProfileReason?: string;
}

/**
 * 节点状态事件载荷。
 * 做什么：描述节点运行状态及耗时、降级、错误信息。
 * 为什么这样做：节点状态完全以后端推送为准，前端不自行推断 started/completed。
 * 输入输出：nodeType 为节点类型，status 为节点状态。
 * 边界条件：startedAtMs、endedAtMs、latencyMs 在开始事件中可能为空。
 * 异常行为：errorCode 非空时表示节点失败或内部错误码。
 */
export interface ChatNodeStatusPayload {
  nodeType: ChatWorkflowNodeType;
  status: ChatNodeStatus;
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;
  degradedReason?: string;
  errorCode?: string;
}

/**
 * 后处理阶段载荷。
 * 做什么：承载后处理开始与完成事件的最小信息。
 * 为什么这样做：普通聊天界面不强打扰用户，但需要在调试面板中识别后处理是否完成。
 * 输入输出：沿用计划生命周期结构，避免重复定义。
 * 边界条件：后处理失败详情仍应结合节点状态与调试时间线展示。
 * 异常行为：无。
 */
export interface ChatPostprocessPayload extends ChatPlanLifecyclePayload {}

/**
 * EVT_CHAT_STATUS 事件载荷。
 * 做什么：承载后端通过 ChatStatusPublisher 推送的 Chat 状态通知载荷。
 * 为什么这样做：前端状态栏根据后端推送的 stage、state 和 display_text
 *             渲染拟人化文案，而非在前端硬编码。
 * 边界条件：is_visible=false 时前端不应展示该状态（如跳过/静默通知）；
 *           is_terminal=true 时前端应清理当前 message_id 的状态展示。
 */
export interface ChatStatusPayload {
  schema_version: string;
  session_id: string;
  message_id: string;
  stage: string;
  state: string;
  display_text: string;
  is_visible: boolean;
  is_terminal: boolean;
  sequence: number;
  timestamp_ms: number;
  error: string;
}

/**
 * MCP 工具执行状态前端投影。
 *
 * 做什么：承载后端通过 EVT_CHAT_STATUS 和 EVT_CHAT_NODE_COMPLETED 推送的
 *         MCP 工具执行状态。前端仅做展示，不做任何业务判断。
 * 为什么这样做：前端是后端的纯状态镜像，所有决策和执行都在 Python 侧完成。
 * 输入输出：状态由后端推送，前端消费并渲染。
 * 边界条件：所有字段都可能为空或 undefined，前端渲染时必须做空值保护。
 */
// ============================================================
// MCP 本地服务器类型定义
// ============================================================

/**
 * 本地 MCP 服务器配置（前端用）。
 *
 * 做什么：定义前端 MCP 面板中本地服务器配置的完整数据结构。
 * 为什么这样做：与后端 API 请求体结构对齐，确保类型安全。
 * 输入输出：用户填写配置 → 提交到后端 API。
 * 边界条件：name 和 command 为必填；args 和 env 可为空。
 * 异常行为：无。
 */
export interface LocalServerConfig {
  /** 服务器唯一名称。 */
  name: string;
  /** 启动命令。 */
  command: string;
  /** 命令参数。 */
  args: string[];
  /** 环境变量键值对。 */
  env: Record<string, string>;
  /** 服务器描述。 */
  description?: string;
  /** 是否启用。 */
  enabled?: boolean;
}

/**
 * 已注册的本地 MCP 服务器（从后端获取）。
 *
 * 做什么：定义后端返回的已注册本地服务器信息。
 * 为什么这样做：列表展示需要显示注册状态、工具数量等信息。
 * 输入输出：来自 GET /api/v1/mcp/local/servers 的响应。
 * 边界条件：tool_count 可能为 0（如果注册后工具均被禁用）。
 */
export interface LocalServerInfo {
  /** 服务器注册 ID。 */
  id: string;
  /** 服务器名称。 */
  name: string;
  /** 启动命令。 */
  command: string;
  /** 命令参数。 */
  args: string[];
  /** 环境变量（后端返回时对敏感值加密）。 */
  env: Record<string, string>;
  /** 服务器描述。 */
  description: string;
  /** 是否启用。 */
  enabled: boolean;
  /** 该服务器下已注册的工具数量。 */
  tool_count: number;
  /** 服务器 endpoint URL（适用于 SSE 模式）。 */
  endpoint_url: string;
  /** 健康状态：unknown / online / offline / error。 */
  health_status: string;
  /** 扩展元数据。 */
  metadata: Record<string, unknown>;
  /** 创建时间（ISO 8601）。 */
  created_at: string;
  /** 更新时间（ISO 8601）。 */
  updated_at: string;
}

/**
 * 批量导入结果。
 *
 * 做什么：定义批量导入操作的后端响应结构。
 */
export interface BatchImportResult {
  /** 成功注册数。 */
  success_count: number;
  /** 失败数。 */
  failed_count: number;
  /** 失败详情。 */
  failures: Array<{
    /** 失败的服务器名称。 */
    name: string;
    /** 失败原因。 */
    error: string;
  }>;
}

export interface MCPToolStatusProjection {
  /** 是否进入了 MCP 工具执行节点。 */
  enteredByCondition: boolean;
  /** 节点进入原因或跳过原因。 */
  conditionReason: string;
  /** 工具执行决策结果（LLM 原始输出镜像）。 */
  decision?: {
    shouldCallTool: boolean;
    toolName: string;
    parameters: Record<string, unknown>;
    reasoning: string;
    requiresUserApproval: boolean;
  };
  /** Agent 推理过程文本。 */
  agentReasoning?: string;
  /** 实际执行的工具名称。 */
  executedToolName?: string;
  /** 执行 ID（雪花算法）。 */
  executionId?: string;
  /** 工具执行输出文本。 */
  outputText?: string;
  /** 错误消息。 */
  errorMessage?: string;
  /** 执行耗时（毫秒）。 */
  latencyMs?: number;
  /** 重试次数。 */
  retryCount?: number;
  /** 工具风险等级。 */
  riskLevel?: string;
  /** 是否降级。 */
  degraded?: boolean;
  /** 降级原因。 */
  degradedReason?: string;
}

// ============================================================
// MCP Skill 类型定义
// ============================================================

/**
 * MCP Skill 完整信息。
 *
 * 做什么：定义前端展示的 MCP Skill 完整数据结构。
 * 为什么这样做：与后端 API 响应结构对齐，确保类型安全。
 * 输入输出：来自 GET /api/v1/mcp/skills 的响应映射。
 * 边界条件：所有字段都可能为空或 undefined，前端渲染时必须做空值保护。
 */
export interface SkillInfo {
  /** Skill ID（雪花算法）。 */
  id: string;
  /** Skill 唯一名称。 */
  name: string;
  /** Skill 功能描述。 */
  description: string;
  /** Skill 版本号。 */
  version: string;
  /** 是否启用。 */
  enabled: boolean;
  /** 扩展元数据。 */
  metadata: Record<string, unknown>;
  /** 创建时间（ISO 8601）。 */
  createdAt: string;
  /** 更新时间（ISO 8601）。 */
  updatedAt: string;
  
  /** 关联工具 */
  tools?: Array<{
    id: string;
    name: string;
    description: string;
    core_purpose: string;
  }>;
  /** 关联 Prompt */
  prompts?: Array<{
    id: string;
    phase: string;
    content: string;
  }>;
  /** 关联资源 */
  resources?: Array<{
    id: string;
    name: string;
    resource_type: string;
    uri: string;
  }>;
}

// ============================================================
// Phase 13：权限治理与前端 Gating 类型定义
// ============================================================

/**
 * 风险等级枚举。
 * 做什么：定义工具调用的安全警戒等级。
 * 为什么这样做：UI 展示风险徽章和拦截策略时需要根据等级区分视觉风格。
 * 边界条件：L0 无需确认，L1 低风险告知，L2 必须用户确认，L3 致命警告+双重确认。
 */
export type RiskLevel = 'L0' | 'L1' | 'L2' | 'L3';

/**
 * 用户审批动作枚举。
 * 做什么：定义用户在 Gating 弹窗中可以选择的审批行为。
 * 为什么这样做：严格限定前端只能发送这两种枚举值，禁止自定义 action。
 */
export type AuthAction = 'APPROVE' | 'REJECT';

/**
 * Phase 13：EVT_TOOL_AUTH_REQUIRED 事件载荷 —— 后端推送的鉴权挂起请求。
 *
 * 做什么：定义 Python 后端通过 SSE/WebSocket 推送的高危工具鉴权挂起事件的数据结构。
 * 为什么这样做：前端审批弹窗（ApprovalCard）渲染所需的全部字段必须来自后端，
 *             前端不可自行拼接或推断任何字段。
 * 输入输出：由 Python 后端 gating/service.py 中的 GatingService 生成并推送。
 * 边界条件：
 *   - risk_level 必须是 'L0' | 'L1' | 'L2' | 'L3' 之一。
 *   - arguments 是任意合法的 JSON 对象，前端必须以原始格式展示。
 *   - 可选字段（goal / skill_info / agent_output）可为 undefined。
 * 异常行为：audit_log_id 为空值或格式非法时，前端 Store 会拒绝入队。
 */
export interface AuthRequiredPayload {
  /** 关联后端审计主键（雪花算法 ID 转换来的 string） */
  audit_log_id: string;
  /** 调用的工具标识（例如 mcp.local_fs.write_file） */
  tool_id: string;
  /** 友好显示的工具名称 */
  tool_name: string;
  /** 告警等级 */
  risk_level: RiskLevel;
  /** 后端策略引擎生成的阻拦原因解释 */
  reason: string;
  /** 参数载荷（例如 {"path":"...", "content":"..."}） */
  arguments: unknown;
  /** AI 当前执行的目标描述 */
  goal?: string;
  /** 相关的 SKILL 元信息 */
  skill_info?: unknown;
  /** SKILL 执行 Agent 的输出信息 */
  agent_output?: string;
}

/**
 * Phase 13：CMD_TOOL_AUTH_RESPONSE 命令载荷 —— 前端发送的用户审批结果。
 *
 * 做什么：定义前端发送给后端的用户审批响应消息结构。
 * 为什么这样做：前端只需将用户的"同意/拒绝"意图原封不动转发给后端，
 *             不参与任何业务逻辑判断。
 * 输入输出：由前端 Gating 组件生成，通过 SSE/WebSocket 发送给 Python 后端。
 * 边界条件：
 *   - action 只能是 'APPROVE' 或 'REJECT'。
 *   - user_feedback 可选，为空字符串时后端按无反馈处理。
 * 异常行为：audit_log_id 为空时后端应拒绝处理并返回错误。
 */
export interface AuthResponsePayload {
  /** 关联后端审计主键（雪花算法 ID 转换来的 string） */
  audit_log_id: string;
  /** 用户审批动作 */
  action: AuthAction;
  /** 用户输入的反馈/修正意见 */
  user_feedback: string;
}

/**
 * Phase 13：EVT_PENDING_AUTHS_SYNC 事件载荷 —— 重连后的完整鉴权列表同步。
 *
 * 做什么：定义后端在重连同步时下发的当前所有 PENDING_APPROVAL 状态鉴权请求列表。
 * 为什么这样做：断线重连后前端必须清洗旧队列再重新入队，同步后端当前有效状态。
 * 输入输出：由 Python 后端在收到 CMD_SYNC_PENDING_AUTHS 时生成。
 * 边界条件：列表可能为空数组，表示当前没有挂起的鉴权请求。
 * 异常行为：无。
 */
export interface PendingAuthsSyncPayload {
  /** 当前所有 PENDING_APPROVAL 状态的鉴权请求列表 */
  requests: AuthRequiredPayload[];
}

// ============================================================
// Phase 9：DAG 工作流事件 Payload 类型定义
// ============================================================

/**
 * DAG Plan 创建事件 Payload — 对应后端 EVT_DAG_PLAN_CREATED。
 * 做什么：承载后端在 Plan 生成完成后推送的完整计划结构。
 * 为什么这样做：前端 DAG 面板需要一次性获取全局目标、State 列表和依赖关系来渲染初始视图。
 * 输入输出：由后端 plan_state_node/plan_service.py 推送，前端 dagWorkflowStore 消费。
 * 边界条件：states 列表可能为空（极端场景），前端需做空值保护。
 * 异常行为：无。
 */
export interface DagPlanCreatedPayload {
  /** 计划 ID（雪花算法） */
  plan_id: string;
  /** 会话 ID */
  session_id: string;
  /** 交互 ID */
  interaction_id: string;
  /** assistant 消息 ID */
  assistant_message_id: string;
  /** 全局目标 */
  global_objective: {
    overall_goal: string;
    success_criteria: string;
    output_format: string;
    constraints: string[];
  };
  /** State 列表（有序） */
  states: Array<{
    state_id: string;
    order_index: number;
    intent: string;
    goal: string;
    completion_criteria: Array<{ field: string; operator: string; value: unknown }>;
    depends_on: string[];
    required_skill_names: string[];
  }>;
  /** 规划推理说明 */
  planning_reason: string;
  /** 已消耗预算 */
  budget_consumed?: { tool_calls: number };
  /** 预算上限 */
  budget_limit?: { max_total_tool_calls: number };
}

/**
 * DAG State 启动事件 Payload — 对应后端 EVT_DAG_STATE_STARTED。
 * 做什么：承载后端进入新 State 时推送的启动信号。
 * 为什么这样做：前端需要高亮当前 State 容器并启动耗时计时器。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onStateStarted 消费。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface DagStateStartedPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** State 顺序索引 */
  order_index: number;
  /** State 目标 */
  goal: string;
}

/**
 * DAG Skill 初筛事件 Payload — 对应后端 EVT_DAG_SKILL_SCREENING。
 * 做什么：承载后端在 State 启动后推送的 Skill 初筛结果。
 * 为什么这样做：前端需要在 State 容器内展示选中的 Skill 标签。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onSkillScreening 消费。
 * 边界条件：selected_skills 可能为空数组。
 * 异常行为：无。
 */
export interface DagSkillScreeningPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** 选中的 Skill 列表 */
  selected_skills: Array<{
    skill_name: string;
    description: string;
    tool_names: string[];
    capability_tags: string[];
  }>;
}

/**
 * DAG Step Plan 生成事件 Payload — 对应后端 EVT_DAG_STEP_PLAN_GENERATED。
 * 做什么：承载后端为当前 State 生成的 Step 计划及其中的原子节点。
 * 为什么这样做：前端需要渲染 Step 列表及其中的节点卡片。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onStepPlanGenerated 消费。
 * 边界条件：steps 列表不为空（至少包含一个 Step）。
 * 异常行为：无。
 */
export interface DagStepPlanPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** Step 列表 */
  steps: Array<{
    step_id: string;
    step_index: number;
    description: string;
    execution_mode: 'parallel' | 'serial';
    nodes: Array<{
      node_id: string;
      node_type: string;
      skill_name?: string;
      tool_name?: string;
      resource_name?: string;
      parameter_hint?: string;
      transform_instruction?: string;
      query_text?: string;
      depends_on: string[];
      gating_required: boolean;
    }>;
  }>;
}

/**
 * DAG 节点启动事件 Payload — 对应后端 EVT_DAG_NODE_STARTED。
 * 做什么：承载后端进入原子节点执行时推送的启动信号。
 * 为什么这样做：前端需要将节点卡片切换为执行态并显示耗时计时器。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onNodeStarted 消费。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface DagNodeStartedPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** Step ID */
  step_id: string;
  /** 节点 ID */
  node_id: string;
  /** 节点类型 */
  node_type: string;
}

/**
 * DAG 节点完成事件 Payload — 对应后端 EVT_DAG_NODE_COMPLETED。
 * 做什么：承载后端原子节点执行完成时推送的结果数据。
 * 为什么这样做：前端需要更新节点状态（成功/失败）、停止计时器并展示输出参数。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onNodeCompleted 消费。
 * 边界条件：outputs 可能为空对象；error_message 仅在 success=false 时有意义。
 * 异常行为：无。
 */
export interface DagNodeCompletedPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** Step ID */
  step_id: string;
  /** 节点 ID */
  node_id: string;
  /** 节点类型 */
  node_type: string;
  /** 是否成功 */
  success: boolean;
  /** 输出参数 */
  outputs: Record<string, unknown>;
  /** 错误信息（失败时） */
  error_message?: string;
  /** 执行耗时（毫秒） */
  latency_ms: number;
  /** 重试次数 */
  retry_count: number;
}

/**
 * DAG 节点 Gating 审批事件 Payload — 对应后端 EVT_DAG_NODE_GATING。
 * 做什么：承载后端因高危工具调用而挂起节点执行时推送的审批请求。
 * 为什么这样做：前端需要在节点卡片上显示「等待审批」状态并弹出 Gating 确认窗口。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onNodeGating 消费。
 * 边界条件：parameters 可能包含任意 JSON 结构。
 * 异常行为：无。
 */
export interface DagNodeGatingPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** 节点 ID */
  node_id: string;
  /** 工具名称 */
  tool_name: string;
  /** 工具参数 */
  parameters: Record<string, unknown>;
  /** 风险等级 */
  risk_level: string;
}

/**
 * DAG State 评估事件 Payload — 对应后端 EVT_DAG_STATE_EVALUATED。
 * 做什么：承载后端对当前 State 完成度评估的结果。
 * 为什么这样做：前端需要展示评估结果（通过/未通过 + 原因）和差距分析。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onStateEvaluated 消费。
 * 边界条件：criteria_checklist 可能为空数组。
 * 异常行为：无。
 */
export interface DagStateEvaluatedPayload {
  /** 计划 ID */
  plan_id: string;
  /** State ID */
  state_id: string;
  /** State 是否满足完成条件 */
  state_satisfied: boolean;
  /** 评估原因 */
  evaluation_reason: string;
  /** 差距分析 */
  gap_analysis: string;
  /** 建议 */
  suggestion: string;
  /** 完成条件检查清单 */
  criteria_checklist: Array<{ field: string; satisfied: boolean; detail: string }>;
}

/**
 * DAG Plan 重构事件 Payload — 对应后端 EVT_DAG_PLAN_REPLANNED。
 * 做什么：承载后端因 State 失败或评估未通过而重新规划时推送的修改信息。
 * 为什么这样做：前端需要更新 State 序列（新增/修改/删除的 State）。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onPlanReplanned 消费。
 * 边界条件：modified_states 包含全量 State 列表（非增量）。
 * 异常行为：无。
 */
export interface DagPlanReplannedPayload {
  /** 计划 ID */
  plan_id: string;
  /** 重构原因 */
  replan_reason: string;
  /** 修改后的 State 列表（全量） */
  modified_states: Array<{
    state_id: string;
    order_index: number;
    intent: string;
    goal: string;
    completion_criteria: Array<{ field: string; operator: string; value: unknown }>;
    depends_on: string[];
  }>;
}

/**
 * DAG Plan 完成事件 Payload — 对应后端 EVT_DAG_PLAN_COMPLETED。
 * 做什么：承载后端 Plan 全部执行完成时推送的执行摘要。
 * 为什么这样做：前端需要展示执行摘要并标记 Plan 为完成态。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onPlanCompleted 消费。
 * 边界条件：execution_highlights 和 execution_issues 可能为空数组。
 * 异常行为：无。
 */
export interface DagPlanCompletedPayload {
  /** 计划 ID */
  plan_id: string;
  /** 总 State 数 */
  total_states: number;
  /** 成功 State 数 */
  succeeded_states: number;
  /** 降级 State 数 */
  degraded_states: number;
  /** 失败 State 数 */
  failed_states: number;
  /** 整体结果描述 */
  overall_result: string;
  /** 执行亮点 */
  execution_highlights: string[];
  /** 执行问题 */
  execution_issues: string[];
}

/**
 * DAG Plan 终止事件 Payload — 对应后端 EVT_DAG_PLAN_TERMINATED。
 * 做什么：承载后端因不可恢复错误而终止 Plan 时推送的终止信息。
 * 为什么这样做：前端需要展示终止原因并标记 Plan 为终止态。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onPlanTerminated 消费。
 * 边界条件：partial_results 可能为空字符串。
 * 异常行为：无。
 */
export interface DagPlanTerminatedPayload {
  /** 计划 ID */
  plan_id: string;
  /** 终止原因 */
  termination_reason: string;
  /** 导致终止的 State ID */
  termination_state_id: string;
  /** 部分结果描述 */
  partial_results: string;
}

/**
 * DAG 预算耗尽事件 Payload — 对应后端 EVT_DAG_BUDGET_EXHAUSTED。
 * 做什么：承载后端检测到工具调用预算即将或已经耗尽时推送的警告。
 * 为什么这样做：前端需要在全局面板展示预算警告并可能触发 Plan 终止。
 * 输入输出：由后端推送，前端 dagWorkflowStore.onBudgetExhausted 消费。
 * 边界条件：level 为 'state' 时仅影响当前 State，'global' 时影响整个 Plan。
 * 异常行为：无。
 */
export interface DagBudgetExhaustedPayload {
  /** 计划 ID */
  plan_id: string;
  /** 预算级别：state 级或 global 级 */
  level: 'state' | 'global';
  /** 已消耗量 */
  consumed: number;
  /** 上限量 */
  limit: number;
}
