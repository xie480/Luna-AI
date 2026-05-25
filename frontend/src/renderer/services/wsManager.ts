/**
 * Luna AI WebSocket 管理器
 * 负责与 Go Runtime 建立 WebSocket 连接，处理消息分发和重连逻辑
 * 严格遵循 Go Runtime 为唯一状态权威的原则，前端仅为状态投影
 */
import { useSessionStore } from '../stores/sessionStore';
import { useSystemStore } from '../stores/systemStore';
import { WS_MSG_TYPE, WSMsgType } from '../../shared/enum';
import {
  WSMessage,
  PongPayload,
  ErrorPayload,
  ChatStreamPayload,
} from '../../shared/types';

/**
 * WebSocket 管理器类
 * 实现断线重连、消息分发、状态同步等功能
 */
class WSManager {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts: number = 0;
  private maxReconnectDelay: number = 10000; // 最大重连延迟 10 秒
  private baseReconnectDelay: number = 1000; // 基础重连延迟 1 秒
  private port: number = 8080; // Go Runtime 默认端口
  private isManualDisconnect: boolean = false; // 标记是否为主动断开

  /**
   * 建立 WebSocket 连接
   * @param port Go Runtime 服务端口
   */
  public connect(port: number = 8080): void {
    this.port = port;
    // 先标记为主动断开，防止 cleanup() 触发 onclose 重连
    this.isManualDisconnect = true;
    this.cleanup();
    // 重置标志，允许新连接断开时重连
    this.isManualDisconnect = false;
    useSystemStore.getState().setConnectionStatus('connecting');

    try {
      this.ws = new WebSocket(`ws://127.0.0.1:${port}/ws`);
      this.setupEventHandlers();
    } catch (err) {
      useSystemStore.getState().addSystemLog(`WebSocket 连接失败: ${err}`);
      this.scheduleReconnect();
    }
  }

  /**
   * 设置 WebSocket 事件处理器
   */
  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      useSystemStore.getState().setConnectionStatus('connected');
      useSystemStore.getState().addSystemLog('WebSocket 已连接');
      this.reconnectAttempts = 0;

      // 连接成功后，请求同步初始状态
      this.send({
        type: WS_MSG_TYPE.CMD_SYNC_INIT_STATE,
        payload: {},
      });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (err) {
        useSystemStore.getState().addSystemLog(`解析消息失败: ${event.data}`);
      }
    };

    this.ws.onclose = (event) => {
      useSystemStore.getState().setConnectionStatus('disconnected');
      useSystemStore.getState().addSystemLog(
        `WebSocket 已断开连接 (code: ${event.code}, reason: ${event.reason})`
      );
      // 只有非主动断开时才触发重连
      if (!this.isManualDisconnect) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      useSystemStore.getState().addSystemLog('WebSocket 错误');
      useSystemStore.getState().setConnectionStatus('disconnected');
    };
  }

  /**
   * 处理接收到的消息
   * 根据消息类型分发到对应的 Store 更新逻辑
   */
  private handleMessage(msg: WSMessage): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();

    // 将消息类型转换为联合类型进行比较
    const msgType = msg.type as WSMsgType;

    switch (msgType) {
      case WS_MSG_TYPE.PONG:
        // Pong 响应
        const pongPayload = msg.payload as PongPayload;
        systemStore.addSystemLog(
          `收到 PONG: trace_id=${msg.trace_id}, source=${pongPayload.source}`
        );
        break;

      case WS_MSG_TYPE.ERROR:
        // 错误消息
        const errorPayload = msg.payload as ErrorPayload;
        systemStore.addSystemLog(
          `收到 ERROR: trace_id=${msg.trace_id}, code=${errorPayload.code}, message=${errorPayload.message}`
        );
        break;

      case WS_MSG_TYPE.CHAT_STREAM:
        // 聊天流式输出
        const chatPayload = msg.payload as ChatStreamPayload;
        this.handleChatStream(chatPayload);
        break;

      case WS_MSG_TYPE.EVT_INIT_STATE:
        // 初始状态同步
        this.handleInitState(msg.payload);
        break;

      case WS_MSG_TYPE.EVT_PLAN_SNAPSHOT:
        // 任务计划快照更新
        sessionStore.updatePlan(msg.payload as any);
        break;

      case WS_MSG_TYPE.EVT_NODE_STATUS_UPDATE:
        // 任务节点状态更新
        const nodePayload = msg.payload as any;
        sessionStore.updateNodeStatus(
          nodePayload.nodeId,
          nodePayload.status,
          nodePayload.progress
        );
        break;

      case WS_MSG_TYPE.EVT_MEMORY_UPDATED:
        // 记忆快照更新
        sessionStore.updateMemory(msg.payload as any);
        break;

      case WS_MSG_TYPE.EVT_DEBUG_LOG:
        // 调试日志推送
        const logPayload = msg.payload as any;
        systemStore.addSystemLog(logPayload.message || String(logPayload));
        break;

      default:
        systemStore.addSystemLog(`收到未知消息类型: ${msg.type}`);
    }
  }

  /**
   * 处理聊天流式输出
   * 使用高频渲染优化策略，避免频繁触发 React 重渲染
   */
  private handleChatStream(payload: ChatStreamPayload): void {
    const sessionStore = useSessionStore.getState();
    const currentSessionId = sessionStore.currentSessionId;

    if (!currentSessionId) {
      useSystemStore.getState().addSystemLog('收到聊天消息但无活跃会话');
      return;
    }

    // 更新消息内容
    sessionStore.updateMessageChunk(currentSessionId, payload.node_id, payload.chunk);

    // 如果流结束，更新消息状态
    if (payload.is_finished) {
      const status = payload.error ? 'error' : 'completed';
      sessionStore.updateMessageStatus(currentSessionId, payload.node_id, status);
      if (payload.error) {
        useSystemStore.getState().addSystemLog(`聊天流错误: ${payload.error}`);
      }
    }
  }

  /**
   * 处理初始状态同步
   * 连接成功后 Go 推送的完整状态快照
   */
  private handleInitState(payload: any): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();

    systemStore.addSystemLog('收到初始状态同步');

    if (payload.sessionId) {
      sessionStore.setSessionId(payload.sessionId);
    }

    if (payload.messages) {
      // 批量设置消息
      sessionStore.appendMessage(payload.sessionId, payload.messages);
    }

    if (payload.activePlan) {
      sessionStore.updatePlan(payload.activePlan);
    }

    if (payload.memory) {
      sessionStore.updateMemory(payload.memory);
    }
  }

  /**
   * 发送消息到 Go Runtime
   * @param data 消息数据对象
   */
  public send(data: { type: string; payload: unknown }): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const message = JSON.stringify({
        ...data,
        timestamp: Date.now(),
        trace_id: `tr-${crypto.randomUUID?.() || Date.now()}`,
      });
      this.ws.send(message);
      useSystemStore.getState().addSystemLog(`发送消息: ${data.type}`);
    } else {
      useSystemStore.getState().addSystemLog('WebSocket 未连接，无法发送消息');
    }
  }

  /**
   * 发送用户聊天消息
   * @param message 用户输入的消息内容
   */
  public sendChatMessage(message: string): void {
    const sessionStore = useSessionStore.getState();
    const sessionId = sessionStore.currentSessionId;

    if (!sessionId) {
      useSystemStore.getState().addSystemLog('无活跃会话，无法发送消息');
      return;
    }

    // 先添加用户消息到 UI（等待 Go 确认）
    const userMsgId = `user-${Date.now()}`;
    sessionStore.appendMessage(sessionId, {
      messageId: userMsgId,
      sessionId,
      role: 'user',
      contentType: 'text',
      content: message,
      timestamp: Date.now(),
      status: 'sending',
    });

    // 发送聊天请求到 Go
    this.send({
      type: WS_MSG_TYPE.CMD_USER_INPUT,
      payload: {
        sessionId,
        message,
        msgId: userMsgId,
      },
    });
  }

  /**
   * 发送 Ping 请求用于测试连接
   */
  public sendPing(): void {
    this.send({
      type: WS_MSG_TYPE.PING,
      payload: {
        timestamp: Date.now(),
      },
    });
  }

  /**
   * 安排重连任务
   * 使用指数退避策略
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    this.reconnectAttempts++;
    const delay = Math.min(
      this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );

    useSystemStore.getState().setConnectionStatus('reconnecting');
    useSystemStore.getState().addSystemLog(
      `将在 ${delay / 1000} 秒后尝试重连 (第 ${this.reconnectAttempts} 次)`
    );

    this.reconnectTimer = setTimeout(() => {
      this.connect(this.port);
    }, delay);
  }

  /**
   * 清理 WebSocket 连接和定时器
   * 注意：先移除事件处理器再关闭连接，防止 onclose 触发重连
   */
  private cleanup(): void {
    if (this.ws) {
      // 先移除所有事件处理器，防止 onclose 触发 scheduleReconnect
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      // 然后关闭连接
      this.ws.close();
      this.ws = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /**
   * 关闭 WebSocket 连接
   */
  public disconnect(): void {
    this.isManualDisconnect = true; // 标记为主动断开，防止触发重连
    this.cleanup();
    useSystemStore.getState().setConnectionStatus('disconnected');
    useSystemStore.getState().addSystemLog('WebSocket 已主动断开');
  }

  /**
   * 获取当前连接状态
   */
  public isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}

// 导出单例实例
export const wsManager = new WSManager();