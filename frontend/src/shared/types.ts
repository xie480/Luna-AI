import { WS_MSG_TYPE } from './enum';

/**
 * WebSocket 消息类型枚举值类型
 * 做什么：从 WS_MSG_TYPE 常量对象中提取类型。
 * 为什么这样做：确保类型定义与常量值保持一致。
 */
type WSMsgType = typeof WS_MSG_TYPE[keyof typeof WS_MSG_TYPE];

/**
 * WebSocket 消息结构
 * 做什么：定义前后端统一的 WebSocket 消息数据结构。
 * 为什么这样做：规范化 WebSocket 消息格式，方便前后端统一处理。
 * 输入输出：泛型 T 代表 payload 字段的具体类型。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface WSMessage<T = unknown> {
  type: WSMsgType;
  trace_id: string;
  payload: T;
}

/**
 * Ping 消息 Payload
 * 做什么：定义 Ping 消息的数据结构。
 * 为什么这样做：规范化 Ping 消息格式。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface PingPayload {
  timestamp: number;
}

/**
 * Pong 消息 Payload
 * 做什么：定义 Pong 消息的数据结构。
 * 为什么这样做：规范化 Pong 消息格式。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface PongPayload {
  timestamp: number;
  source: string;
}

/**
 * Error 消息 Payload
 * 做什么：定义 Error 消息的数据结构。
 * 为什么这样做：规范化 Error 消息格式。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface ErrorPayload {
  code: number;
  message: string;
}

/**
 * ChatRequest 消息 Payload
 * 做什么：定义 ChatRequest 消息的数据结构。
 * 为什么这样做：规范化 ChatRequest 消息格式。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface ChatRequestPayload {
  message: string;
}

/**
 * ChatStream 消息 Payload
 * 做什么：定义 ChatStream 消息的数据结构。
 * 为什么这样做：规范化 ChatStream 消息格式。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export interface ChatStreamPayload {
  chunk: string;
  is_finished: boolean;
  node_id: string;
  error?: string;
}