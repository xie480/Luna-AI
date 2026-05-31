/**
 * Luna AI WebSocket 管理器
 * 负责与 Go Runtime 建立 WebSocket 连接，处理消息分发和重连逻辑
 * 严格遵循 Go Runtime 为唯一状态权威的原则，前端仅为状态投影
 *
 * 流式渲染改造（对齐 streaming_rendering_plan.md）：
 * - CHAT_STREAM → 解析内含的 type 字段（emotion_update / reply_chunk），
 *   以 CustomEvent 桥接到 BubbleStack（气泡渲染）和 Live2DView（情绪同步）。
 * - EVT_EMOTION_UPDATE / EVT_REPLY_CHUNK 作为独立消息类型直接处理。
 *
 * Phase 4 增强（可观测性）：
 * - 接收消息时自动提取并同步 trace_id 到 systemStore
 * - 新增 EVT_TELEMETRY_TRACE / EVT_TELEMETRY_METRICS 消息处理
 * - send() 方法优先使用 systemStore.currentTraceID 作为 TraceID 源
 *
 * Phase 5 增强（近期记忆）：
 * - EVT_INIT_STATE 处理时，将 recentQA 更新到 sessionStore
 * - CHAT_STREAM 流结束后，不再自动触发 addRecentQA（废弃基于 is_finished 的延迟机制）
 * - 改为监听 luna:all-bubbles-complete 自定义事件，由前端确认所有气泡渲染完成后才插入近期记忆
 */
import { useSessionStore } from '../stores/sessionStore';
import { useSystemStore, type EmotionState } from '../stores/systemStore';
import { useTelemetryStore, TelemetrySpan, MetricsDataPoint } from '../stores/telemetryStore';
import { EMOTION_EXPRESSIONS } from '../constants/emotionExpressions';
import { WS_MSG_TYPE, WSMsgType } from '../../shared/enum';
import { generateId } from '../../shared/utils/snowflake';
import {
  WSMessage,
  PongPayload,
  ErrorPayload,
  ChatStreamPayload,
  EmotionUpdatePayload,
  ReplyChunkPayload,
  ChatMessage,
  InitStatePayload,
  InteractionQA,
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

  // Phase 5: 记录当前正在交互的用户消息，用于气泡渲染完成后插入近期记忆
  private pendingUserMessage: string = '';
  private pendingUserMsgId: string = '';
  private pendingAssistantContent: string = '';
  // 标记当前是否有等待插入的近期记忆数据
  private hasPendingMemory: boolean = false;
  // 标记是否已注册 luna:all-bubbles-complete 监听器
  private isMemoryListenerRegistered: boolean = false;

  /**
   * Phase 5: 注册 luna:all-bubbles-complete 事件监听
   * 当所有气泡渲染和消失动画完成时，插入近期记忆
   * 只注册一次，避免重复监听
   */
  private registerAllBubblesCompleteListener(): void {
    if (this.isMemoryListenerRegistered) return;
    this.isMemoryListenerRegistered = true;

    window.addEventListener('luna:all-bubbles-complete', () => {
      // 检查是否有待插入的近期记忆数据
      if (!this.hasPendingMemory) return;

      const newQA: InteractionQA = {
        msgId: this.pendingUserMsgId,
        userContent: this.pendingUserMessage,
        assistantContent: this.pendingAssistantContent,
        timestamp: Math.floor(Date.now() / 1000),
      };
      useSessionStore.getState().addRecentQA(newQA);

      // 清理临时状态，准备下一轮对话
      this.pendingUserMessage = '';
      this.pendingUserMsgId = '';
      this.pendingAssistantContent = '';
      this.hasPendingMemory = false;
    });
  }

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

    // Phase 4 增强：如果 Go 端返回的消息携带了 trace_id，同步到 systemStore
    // 确保后端的 TraceID 覆盖前端的初版（后端是权威）
    if (msg.trace_id && msg.trace_id !== systemStore.currentTraceID) {
      systemStore.setCurrentTraceID(msg.trace_id);
    }

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
        // 聊天流式输出 —— 内含 type 字段区分 emotion_update / reply_chunk
        const chatPayload = msg.payload as ChatStreamPayload;
        this.handleChatStream(chatPayload);
        break;

      // === 流式渲染独立事件（streaming_rendering_plan.md §3.1）===
      case WS_MSG_TYPE.EVT_EMOTION_UPDATE:
        // 独立情绪更新事件
        const emotionPayload = msg.payload as EmotionUpdatePayload;
        systemStore.setEmotion(emotionPayload.emotion);
        // 同步触发全局事件供 Live2D 消费
        window.dispatchEvent(
          new CustomEvent('luna:emotion-update', { detail: { emotion: emotionPayload.emotion } })
        );
        break;

      case WS_MSG_TYPE.EVT_REPLY_CHUNK:
        // 独立回复文本块事件
        const replyPayload = msg.payload as ReplyChunkPayload;
        // 触发气泡显示事件
        if (replyPayload.chunk && replyPayload.chunk.trim()) {
          const duration = Math.max(3000, replyPayload.chunk.length * 200);
          window.dispatchEvent(
            new CustomEvent('luna:show-bubble', {
              detail: { text: replyPayload.chunk, duration },
            })
          );
        }
        break;

      case WS_MSG_TYPE.EVT_INIT_STATE:
        // 初始状态同步
        this.handleInitState(msg.payload as InitStatePayload);
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

      // === Phase 4 新增：可观测性相关 ===
      case WS_MSG_TYPE.EVT_TELEMETRY_TRACE:
        // Go 推送的链路 Span（仅在诊断面板开启时推送）
        const spanPayload = msg.payload as TelemetrySpan;
        const telemetryStore = useTelemetryStore.getState();
        const updatedSpans = [...telemetryStore.traceSpans, spanPayload];
        telemetryStore.setTraceSpans(updatedSpans, updatedSpans.length);
        break;

      case WS_MSG_TYPE.EVT_TELEMETRY_METRICS:
        // Go 推送的实时监控指标（每秒推送一次）
        const metricsPayload = msg.payload as MetricsDataPoint;
        const telemetryStore = useTelemetryStore.getState();
        const updatedMetrics = [...telemetryStore.metrics, metricsPayload].slice(-60);
        telemetryStore.setMetrics(updatedMetrics);
        break;

      default:
        systemStore.addSystemLog(`收到未知消息类型: ${msg.type}`);
    }
  }

  /**
   * 处理聊天流式输出（CHAT_STREAM 消息）
   * 按 payload.type 拆分为情绪更新和回复文本块
   *
   * Phase 5 重构：不再在 is_finished 时自动触发 addRecentQA，
   * 改为由 luna:all-bubbles-complete 事件驱动
   */
  private handleChatStream(payload: ChatStreamPayload): void {
    const systemStore = useSystemStore.getState();
    const msgType = payload.type || 'reply_chunk';

    if (msgType === 'emotion_update') {
      // 情绪更新：更新 Live2D 表情状态（streaming_rendering_plan.md §3.2）
      // 标准化情绪字符串：去除首尾空格，转换为首字母大写
      const rawEmotion = payload.chunk as string;
      const normalizedEmotion = rawEmotion ? rawEmotion.trim() : 'neutral';
      
      // 类型检查：确保 emotion 是有效的 EmotionState
      const validEmotions = ['neutral', ...Object.keys(EMOTION_EXPRESSIONS)] as const;
      const emotionValue = validEmotions.includes(normalizedEmotion as any) 
        ? normalizedEmotion as EmotionState 
        : 'neutral'; // 默认值
      
      systemStore.setEmotion(emotionValue);
      systemStore.addSystemLog(`[WS] 收到情绪更新: ${rawEmotion} -> ${emotionValue}`);
      // 同步触发全局事件供 Live2D 消费（与 EVT_EMOTION_UPDATE 路径一致）
      window.dispatchEvent(
        new CustomEvent('luna:emotion-update', { detail: { emotion: emotionValue } })
      );
      return;
    }

    if (msgType === 'reply_chunk') {
      // 回复文本块：通过 CustomEvent 桥接到 BubbleStack（streaming_rendering_plan.md §3.3）
      if (payload.chunk && payload.chunk.trim()) {
        const duration = Math.max(3000, payload.chunk.length * 200);
        window.dispatchEvent(
          new CustomEvent('luna:show-bubble', {
            detail: { text: payload.chunk, duration },
          })
        );
      }

      // 追加到 sessionStore 的消息内容中（用于完整对话历史记录持久化）
      const sessionStore = useSessionStore.getState();
      const currentSessionId = sessionStore.currentSessionId;
      if (currentSessionId) {
        sessionStore.updateMessageChunk(currentSessionId, payload.node_id, payload.chunk);
      }

      // Phase 5: 累积助手回复内容，用于气泡渲染完成后插入近期记忆
      this.pendingAssistantContent += payload.chunk;

      // 如果流结束，更新消息状态并标记有等待插入的近期记忆数据
      if (payload.is_finished) {
        const status = payload.error ? 'error' : 'completed';
        if (currentSessionId) {
          sessionStore.updateMessageStatus(currentSessionId, payload.node_id, status);
        }
        if (payload.error) {
          systemStore.addSystemLog(`聊天流错误: ${payload.error}`);
        }

        // Phase 5: 标记有待插入的记忆数据，等待 luna:all-bubbles-complete 事件触发后真正插入
        this.hasPendingMemory = true;
      }
    }
  }

  /**
   * 处理初始状态同步
   * 连接成功后 Go 推送的完整状态快照
   * Phase 5 改造：仅处理 sessionId 和 recentQA，移除旧版 messages/plan/memory 处理
   */
  private handleInitState(payload: InitStatePayload): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();

    systemStore.addSystemLog('收到初始状态同步');

    if (payload.sessionId) {
      sessionStore.setSessionId(payload.sessionId);
    }

    if (payload.recentQA) {
      sessionStore.setRecentQA(payload.recentQA);
    }
  }

  /**
   * 发送消息到 Go Runtime
   * @param data 消息数据对象
   *
   * Phase 4 增强：
   * 优先使用 systemStore 中维护的全局 TraceID（由 useTraceContext 设置）
   * 如果不存在则新生成一个
   */
  public send(data: { type: string; payload: unknown }): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const currentTraceID = useSystemStore.getState().currentTraceID;
      const traceID = currentTraceID || `tr-${generateId()}`;

      const message = JSON.stringify({
        ...data,
        timestamp: Date.now(),
        trace_id: traceID,
      });
      this.ws.send(message);
      useSystemStore.getState().addSystemLog(`发送消息: ${data.type}, trace_id=${traceID}`);
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

    // 注册 luna:all-bubbles-complete 事件监听（只在首次调用时注册一次）
    this.registerAllBubblesCompleteListener();

    // 【问题5修复】统一标识符生成规范，消息 ID 移除任何类型的前缀，全面采用雪花算法
    const userMsgId = generateId();

    // Phase 5: 记录当前用户输入，用于气泡渲染完成后插入近期记忆
    this.pendingUserMessage = message;
    this.pendingUserMsgId = userMsgId;
    this.pendingAssistantContent = '';
    this.hasPendingMemory = false;

    sessionStore.appendMessage(sessionId, {
      messageId: userMsgId,
      sessionId,
      role: 'user',
      contentType: 'text',
      content: message,
      timestamp: Date.now(),
      status: 'sending',
    });

    // 发送聊天请求到 Go（不再携带全量历史记录，由后端 Redis 管理）
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
