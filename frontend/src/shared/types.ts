import {
  CHAT_MODE,
  CHAT_NODE_STATUS,
  CHAT_PLAN_PRESET,
  CHAT_WORKFLOW_EVENT_TYPE,
  CHAT_WORKFLOW_NODE_TYPE,
  CHAT_WORKFLOW_SCHEMA_VERSION,
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
 * 为什么这样做：Plan 投影视图和消息元数据都需要持有模式信息。
 * 输入输出：无。
 * 边界条件：Phase 8.5 仅支持 [`CHAT_MODE.DAILY_CHAT`](frontend/src/shared/enum.ts)。
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
 * 为什么这样做：前端必须展示“条件已评估 / 未进入原因”，而不是自行推导是否跳过。
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
