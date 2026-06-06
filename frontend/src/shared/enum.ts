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
