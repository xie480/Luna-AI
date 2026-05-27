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
 */
export interface PingPayload {
  timestamp: number;
}

/**
 * Pong 消息 Payload
 * 做什么：定义 Pong 消息的数据结构。
 * 为什么这样做：规范化 Pong 消息格式。
 */
export interface PongPayload {
  timestamp: number;
  source: string;
}

/**
 * Error 消息 Payload
 * 做什么：定义 Error 消息的数据结构。
 * 为什么这样做：规范化 Error 消息格式。
 */
export interface ErrorPayload {
  code: number;
  message: string;
}

/**
 * ChatMessage 定义单条对话消息，用于多轮对话历史记录
 * 做什么：定义对话消息的数据结构，用于前端维护历史记录和发送给后端。
 * 为什么这样做：确保前端发送给后端的 history 格式与后端期望一致。
 * 边界条件：
 *   - role 只能是 'user' | 'assistant' | 'system'
 *   - content 不能为空字符串
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * ChatRequest 消息 Payload（增强版，支持多轮历史记录和系统提示词）
 * 做什么：定义 ChatRequest 消息的完整数据结构。
 * 为什么这样做：支持多轮对话，让 AI 模型能够感知对话上下文。
 * 边界条件：
 *   - history 为空数组时表示首次对话
 *   - system_prompt 为空时后端使用默认提示词
 */
export interface ChatRequestPayload {
  message: string;
  /** 多轮对话历史记录，按时间正序排列（最旧的在前） */
  history?: ChatMessage[];
  /** 可选的自定义系统提示词，为空时使用后端默认值 */
  system_prompt?: string;
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
  type: string;
  chunk: string;
  is_finished: boolean;
  node_id: string;
  error?: string;
}
