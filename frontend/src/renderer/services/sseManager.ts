/**
 * Luna AI SSE（Server-Sent Events）管理器
 *
 * 做什么：通过 EventSource 接收后端实时推送，
 *        通过 fetch HTTP API 发送业务请求。
 *
 * 为什么这样做：实时推送统一使用 SSE，
 *            业务请求通过普通 HTTP POST/GET 完成。
 * 
 * 核心变更：
 * - 移除 new WebSocket，改为 new EventSource('/sse/notifications')
 * - 移除心跳 Ping/Pong，SSE 自带心跳机制（每5秒 HEARTBEAT 事件）
 * - 移除指数退避重连，EventSource 原生支持自动重连
 * - 所有业务请求改为 fetch 调用 HTTP API
 * - 保持 CustomEvent 分发兼容层，UI 组件无需改动
 * 
 * Bug 修复记录：
 * - Bug 1 修复：sendChatMessage 中添加 assistant 消息占位，
 *   确保 isWaiting 状态在 fetch 响应和 SSE 首块到达之间保持连续，
 *   避免加载动画提前终止后又被重复触发。
 * - 近期记忆插入时机优化：将 recentQA 更新完全交由
 *   luna:all-bubbles-complete 事件驱动，确保插入时机与气泡渲染
 *   队列生命周期严格对齐。
 */
import { AI_SERVICE_BASE_URL, AI_SERVICE_PORT } from '../appConfig';
import { useSessionStore } from '../stores/sessionStore';
import { useSystemStore, type EmotionState } from '../stores/systemStore';
import { useTelemetryStore, TelemetrySpan, MetricsDataPoint } from '../stores/telemetryStore';
import { EMOTION_EXPRESSIONS } from '../constants/emotionExpressions';
import { WS_MSG_TYPE, WSMsgType } from '../../shared/enum';
import { generateId } from '../../shared/utils/snowflake';
import { createErrorToast } from '../stores/errorToastStore';
import { reportError } from '../services/errorLogService';
import {
  WSMessage,
  PongPayload,
  ErrorPayload,
  ChatStreamPayload,
  EmotionUpdatePayload,
  ReplyChunkPayload,
  InitStatePayload,
  InteractionQA,
} from '../../shared/types';

/**
 * SSE 事件结构（后端推送的统一格式）
 */
interface SSEEvent {
  type: string;
  trace_id: string;
  payload: unknown;
}

/**
 * SSE 管理器类
 * 替代原有的 WSManager，使用 EventSource + fetch 实现通信。
 */
class SSEManager {
  private eventSource: EventSource | null = null;
  private backendUrl: string = AI_SERVICE_BASE_URL;
  private isManualDisconnect: boolean = false;

  // 记录当前正在交互的用户消息，用于气泡渲染完成后插入近期记忆
  private pendingUserMessage: string = '';
  private pendingUserMsgId: string = '';
  private pendingAssistantContent: string = '';
  private hasPendingMemory: boolean = false;
  private isMemoryListenerRegistered: boolean = false;

  /**
   * 注册 luna:all-bubbles-complete 事件监听
   * 当所有气泡渲染和消失动画完成时，插入近期记忆
   *
   * 优化说明：此监听器是 recentQA 更新的唯一入口。
   * handleChatStream 的 is_finished 处理中不再直接插入，
   * 而是只标记 hasPendingMemory=true，由本监听器在气泡
   * 队列完全清空后执行实际插入，确保与气泡生命周期对齐。
   */
  private registerAllBubblesCompleteListener(): void {
    if (this.isMemoryListenerRegistered) return;
    this.isMemoryListenerRegistered = true;

    window.addEventListener('luna:all-bubbles-complete', () => {
      if (!this.hasPendingMemory) return;

      const newQA: InteractionQA = {
        msgId: this.pendingUserMsgId,
        userContent: this.pendingUserMessage,
        assistantContent: this.pendingAssistantContent,
        timestamp: Math.floor(Date.now() / 1000),
      };
      useSessionStore.getState().addRecentQA(newQA);

      this.pendingUserMessage = '';
      this.pendingUserMsgId = '';
      this.pendingAssistantContent = '';
      this.hasPendingMemory = false;
    });
  }

  /**
   * 建立 SSE 连接
   * @param port Python AI Service 服务端口
   */
  public connect(port: number = AI_SERVICE_PORT): void {
    this.backendUrl = `http://127.0.0.1:${port}`;
    this.isManualDisconnect = true;
    this.disconnect();
    this.isManualDisconnect = false;

    useSystemStore.getState().setConnectionStatus('connecting');

    try {
      // EventSource 会自动处理重连，无需手动实现
      this.eventSource = new EventSource(`${this.backendUrl}/sse/notifications`);
      this.setupEventHandlers();
    } catch (err) {
      const errMsg = `SSE 连接失败: ${err}`;
      useSystemStore.getState().addSystemLog(errMsg);
      // 显示全局错误提示并持久化
      createErrorToast('ERROR', 'SSE', errMsg);
      reportError('sse', errMsg).catch(() => {});
    }
  }

  /**
   * 设置 SSE 事件处理器
   */
  private setupEventHandlers(): void {
    if (!this.eventSource) return;

    // 连接成功事件
    this.eventSource.addEventListener('connected', (event) => {
      useSystemStore.getState().setConnectionStatus('connected');
      useSystemStore.getState().addSystemLog('SSE 已连接 (event)');
      
      try {
        const data = JSON.parse(event.data);
        if (data.payload && data.payload.is_ready) {
          useSystemStore.getState().setBackendReady(true);
        }
      } catch (e) {}

      // 连接成功后，请求同步初始状态
      this.syncInitState();
    });

    this.eventSource.onopen = () => {
      useSystemStore.getState().setConnectionStatus('connected');
      useSystemStore.getState().addSystemLog('SSE 已连接 (onopen)');
      this.syncInitState();
    };

    // 监听 SERVER_READY 事件
    this.eventSource.addEventListener('SERVER_READY', () => {
      useSystemStore.getState().setBackendReady(true);
      useSystemStore.getState().addSystemLog('后端服务已完全就绪');
    });

    // 心跳事件（仅用于维持连接，不做 UI 操作）
    this.eventSource.addEventListener('heartbeat', () => {
      useSystemStore.getState().setConnectionStatus('connected');
    });

    // CHAT_STREAM 事件
    this.eventSource.addEventListener('CHAT_STREAM', (event) => {
      try {
        const sseEvent: SSEEvent = JSON.parse(event.data);
        // 转换为旧的 WSMessage 格式再分发
        const msg: WSMessage = {
          type: sseEvent.type as WSMsgType,
          trace_id: sseEvent.trace_id,
          payload: sseEvent.payload,
        };
        this.handleMessage(msg);
      } catch (err) {
        const errMsg = `解析 SSE 消息失败: ${err}`;
        useSystemStore.getState().addSystemLog(errMsg);
        // 显示全局错误提示并持久化
        createErrorToast('ERROR', 'SSE', errMsg);
        reportError('sse', errMsg).catch(() => {});
      }
    });

    // EVT_INIT_STATE 事件
    this.eventSource.addEventListener('EVT_INIT_STATE', (event) => {
      try {
        const sseEvent: SSEEvent = JSON.parse(event.data);
        const msg: WSMessage = {
          type: sseEvent.type as WSMsgType,
          trace_id: sseEvent.trace_id,
          payload: sseEvent.payload,
        };
        this.handleMessage(msg);
      } catch (err) {
        useSystemStore.getState().addSystemLog(`解析 EVT_INIT_STATE 消息失败: ${err}`);
      }
    });

    // 通用消息事件（兜底处理所有未注册的事件类型）
    this.eventSource.onmessage = (event) => {
      try {
        const sseEvent: SSEEvent = JSON.parse(event.data);
        if (sseEvent.type === 'HEARTBEAT') return; // 心跳已由事件监听处理
        if (sseEvent.type === 'CHAT_STREAM') return; // CHAT_STREAM 已由事件监听处理

        const msg: WSMessage = {
          type: sseEvent.type as WSMsgType,
          trace_id: sseEvent.trace_id,
          payload: sseEvent.payload,
        };
        this.handleMessage(msg);
      } catch (err) {
        const errMsg = `解析 SSE 消息失败: ${err}`;
        useSystemStore.getState().addSystemLog(errMsg);
        // 显示全局错误提示并持久化
        createErrorToast('ERROR', 'SSE', errMsg);
        reportError('sse', errMsg).catch(() => {});
      }
    };

    // 错误处理
    this.eventSource.onerror = () => {
      useSystemStore.getState().addSystemLog('SSE 连接错误');
      useSystemStore.getState().setConnectionStatus('disconnected');
      // EventSource 会自动重连，不需要手动处理
    };
  }

  /**
   * 处理接收到的 SSE 消息
   */
  private handleMessage(msg: WSMessage): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();

    if (msg.trace_id && msg.trace_id !== systemStore.currentTraceID) {
      systemStore.setCurrentTraceID(msg.trace_id);
    }

    const msgType = msg.type as WSMsgType;

    switch (msgType) {
      case WS_MSG_TYPE.PONG: {
        const pongPayload = msg.payload as PongPayload;
        systemStore.addSystemLog(`收到 PONG: trace_id=${msg.trace_id}, source=${pongPayload.source}`);
        if (pongPayload.source === 'python-ai-service') {
          systemStore.setAiConnectionStatus('connected');
        }
        break;
      }

      case WS_MSG_TYPE.ERROR: {
        const errorPayload = msg.payload as ErrorPayload;
        systemStore.addSystemLog(
          `收到 ERROR: trace_id=${msg.trace_id}, code=${errorPayload.code}, message=${errorPayload.message}`
        );
        if (errorPayload.code === 5000 && errorPayload.message === 'AI service unavailable') {
          systemStore.setAiConnectionStatus('disconnected');
        }
        break;
      }

      case WS_MSG_TYPE.CHAT_STREAM: {
        const chatPayload = msg.payload as ChatStreamPayload;
        this.handleChatStream(chatPayload);
        break;
      }

      case WS_MSG_TYPE.EVT_EMOTION_UPDATE: {
        const emotionPayload = msg.payload as EmotionUpdatePayload;
        const validEmotions = ['neutral', ...Object.keys(EMOTION_EXPRESSIONS)] as const;
        type ValidEmotion = typeof validEmotions[number];
        const rawEmotion = emotionPayload.emotion;
        const emotionValue: EmotionState = validEmotions.includes(rawEmotion as ValidEmotion)
          ? (rawEmotion as EmotionState)
          : 'neutral';
        systemStore.setEmotion(emotionValue);
        window.dispatchEvent(
          new CustomEvent('luna:emotion-update', { detail: { emotion: emotionValue } })
        );
        break;
      }

      case WS_MSG_TYPE.EVT_REPLY_CHUNK: {
        const replyPayload = msg.payload as ReplyChunkPayload;
        if (replyPayload.chunk && replyPayload.chunk.trim()) {
          const duration = Math.max(3000, replyPayload.chunk.length * 200);
          window.dispatchEvent(
            new CustomEvent('luna:show-bubble', {
              detail: { text: replyPayload.chunk, duration },
            })
          );
        }
        break;
      }

      case WS_MSG_TYPE.EVT_INIT_STATE: {
        this.handleInitState(msg.payload as InitStatePayload);
        break;
      }

      case WS_MSG_TYPE.EVT_PLAN_SNAPSHOT: {
        sessionStore.updatePlan(msg.payload as any);
        break;
      }

      case WS_MSG_TYPE.EVT_NODE_STATUS_UPDATE: {
        const nodePayload = msg.payload as any;
        sessionStore.updateNodeStatus(nodePayload.nodeId, nodePayload.status, nodePayload.progress);
        break;
      }

      case WS_MSG_TYPE.EVT_MEMORY_UPDATED: {
        sessionStore.updateMemory(msg.payload as any);
        break;
      }

      case WS_MSG_TYPE.EVT_DEBUG_LOG: {
        const logPayload = msg.payload as any;
        systemStore.addSystemLog(logPayload.message || String(logPayload));
        break;
      }

      case WS_MSG_TYPE.EVT_TELEMETRY_TRACE: {
        const spanPayload = msg.payload as TelemetrySpan;
        const telemetryStoreTrace = useTelemetryStore.getState();
        const updatedSpans = [...telemetryStoreTrace.traceSpans, spanPayload];
        telemetryStoreTrace.setTraceSpans(updatedSpans, updatedSpans.length);
        break;
      }

      case WS_MSG_TYPE.EVT_TELEMETRY_METRICS: {
        const metricsPayload = msg.payload as MetricsDataPoint;
        const telemetryStoreMetrics = useTelemetryStore.getState();
        const updatedMetrics = [...telemetryStoreMetrics.metrics, metricsPayload].slice(-60);
        telemetryStoreMetrics.setMetrics(updatedMetrics);
        break;
      }

      case WS_MSG_TYPE.RES_CALENDAR_METADATA: {
        const metaPayload = msg.payload as { year_month: string; active_dates: string[] };
        import('../stores/historyStore').then(({ useHistoryStore }) => {
          useHistoryStore.getState().setCalendarMetadata(metaPayload.year_month, metaPayload.active_dates || []);
        });
        break;
      }

      case WS_MSG_TYPE.RES_CHAT_HISTORY: {
        const historyPayload = msg.payload as { date: string; messages: any[] };
        import('../stores/historyStore').then(({ useHistoryStore }) => {
          useHistoryStore.getState().setChatHistory(historyPayload.date, historyPayload.messages);
        });
        break;
      }

      default:
        systemStore.addSystemLog(`收到未知消息类型: ${msg.type}`);
    }
  }

  /**
   * 处理聊天流式输出（通过 SSE 接收的 ChatStreamPayload）
   *
   * Bug 1 修复说明：
   * - 将 emotion_update 处理从 return 改为不阻断后续处理路径的方式，
   *   确保所有消息类型都能正确参与状态流转。
   * - 在第一次调用时立即获取 sessionStore 引用，避免每次调用
   *   getState() 可能产生的陈旧引用问题。
   *
   * 近期记忆插入时机优化说明：
   * - is_finished 处理中不再直接插入 recentQA。
   * - 改为仅设置 hasPendingMemory=true，交由气泡完成事件
   *   (luna:all-bubbles-complete) 触发实际插入。
   * - 确保 recentQA 更新与气泡渲染队列生命周期严格对齐。
   */
  private handleChatStream(payload: ChatStreamPayload): void {
    const systemStore = useSystemStore.getState();
    const sessionStore = useSessionStore.getState();
    const currentSessionId = sessionStore.currentSessionId;
    const msgType = payload.type || 'reply_chunk';

    // ---- 第一步：处理所有消息类型共有的内容更新 ----
    if (msgType === 'emotion_update') {
      // 情绪更新：不涉及内容拼接，仅更新状态和触发事件
      const rawEmotion = payload.chunk as string;
      const normalizedEmotion = rawEmotion ? rawEmotion.trim() : 'neutral';
      const validEmotions = ['neutral', ...Object.keys(EMOTION_EXPRESSIONS)] as const;
      const emotionValue = validEmotions.includes(normalizedEmotion as any)
        ? normalizedEmotion as EmotionState
        : 'neutral';
      systemStore.setEmotion(emotionValue);
      systemStore.addSystemLog(`[SSE] 收到情绪更新: ${rawEmotion} -> ${emotionValue}`);
      window.dispatchEvent(
        new CustomEvent('luna:emotion-update', { detail: { emotion: emotionValue } })
      );
    } else if (msgType === 'reply_chunk') {
      // 回复块：拼接内容和触发气泡渲染
      if (payload.chunk && payload.chunk.trim()) {
        const duration = Math.max(3000, payload.chunk.length * 200);
        window.dispatchEvent(
          new CustomEvent('luna:show-bubble', {
            detail: { text: payload.chunk, duration },
          })
        );
      }

      if (currentSessionId) {
        sessionStore.updateMessageChunk(currentSessionId, payload.node_id, payload.chunk);
      }

      this.pendingAssistantContent += payload.chunk;
    }

    // ---- 第二步：统一处理所有消息类型的完成标记 ----
    // 注意：is_finished 标记独立于 msgType，无论 emotion_update 还是
    // reply_chunk 都可能携带 is_finished=true（实际后端只有 reply_chunk 会带）
    if (payload.is_finished) {
      // 2a. 更新消息状态（释放 isWaiting 锁定）
      const status = payload.error ? 'error' : 'completed';
      if (currentSessionId) {
        sessionStore.updateMessageStatus(currentSessionId, payload.node_id, status);
      }

      // 2b. 处理错误通知
      if (payload.error) {
        const errMsg = `生成失败: ${payload.error}`;
        systemStore.addSystemLog(errMsg);
        window.dispatchEvent(new CustomEvent('luna:notification', {
          detail: { message: errMsg, type: 'error', source: 'chat_stream' }
        }));
      }

      // 2c. 标记待处理记忆，供气泡完成事件的监听器使用
      // 优化：不再在此处直接插入 recentQA，而是等待气泡队列完全清空后，
      // 由 luna:all-bubbles-complete 事件触发插入，确保与气泡生命周期对齐。
      this.hasPendingMemory = true;

      // 2d. 如果内容为空或出错，立即触发气泡完成事件（无需等待气泡动画）
      if (payload.error || !this.pendingAssistantContent.trim()) {
        window.dispatchEvent(new CustomEvent('luna:all-bubbles-complete'));
      }

      // 2e. 当日聊天记录实时更新
      import('../stores/historyStore').then(({ useHistoryStore }) => {
        const historyState = useHistoryStore.getState();
        const now = new Date();
        const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        historyState.addCalendarRecord(todayStr);
        if (historyState.selectedDate === todayStr) {
          historyState.fetchChatHistory(todayStr);
        }
      });
    }
  }

  /**
   * 处理初始状态同步
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
   * 同步初始状态（通过 HTTP POST 调用）
   */
  private async syncInitState(): Promise<void> {
    const traceId = `web-${generateId()}`;
    try {
      const resp = await fetch(`${this.backendUrl}/api/init_state`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-ID': traceId,
        },
        body: JSON.stringify({}),
      });
      if (resp.ok) {
        const data = await resp.json();
        // Go Runtime 会返回 EVT_INIT_STATE 格式的数据
        if (data.payload) {
          this.handleInitState(data.payload as InitStatePayload);
        }
      }
    } catch (err) {
      useSystemStore.getState().addSystemLog(`初始化状态同步失败: ${err}`);
    }
  }

  /**
   * 发送用户聊天消息（通过 HTTP POST 调用）
   *
   * Bug 1 修复说明：
   * - 在发送 HTTP 请求之前，预先插入一条 assistant 消息占位（status: streaming），
   *   确保 isWaiting 状态在 fetch 快速返回和 SSE 首块到达之间保持连续。
   * - 原先的流程：用户消息 sending → fetch 返回 200 后变为 completed → isWaiting=false
   *   → SSE 首块到达自动创建 streaming assistant 消息 → isWaiting=true（加载动画闪烁重启）
   * - 修复后流程：用户消息 sending + assistant 消息 streaming → fetch 返回后用户消息变为
   *   completed（isWaiting 仍为 true，因 assistant 尚在 streaming）
   *   → SSE 首块到达更新 content → is_finished 后 assistant 变为 completed → isWaiting=false
   */
  public sendChatMessage(message: string): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();
    const sessionId = sessionStore.currentSessionId;

    if (!sessionId) {
      systemStore.addSystemLog('无活跃会话，无法发送消息');
      return;
    }

    this.registerAllBubblesCompleteListener();

    const userMsgId = generateId();
    const assistantMsgId = generateId();
    this.pendingUserMessage = message;
    this.pendingUserMsgId = userMsgId;
    this.pendingAssistantContent = '';
    this.hasPendingMemory = false;

    // 追加用户消息（sending 状态）
    sessionStore.appendMessage(sessionId, {
      messageId: userMsgId,
      sessionId,
      role: 'user',
      contentType: 'text',
      content: message,
      timestamp: Date.now(),
      status: 'sending',
    });

    // Bug 1 修复：预先插入 assistant 消息占位（streaming 状态）
    // 确保 isWaiting 在 HTTP 响应和 SSE 首块之间保持为 true
    sessionStore.appendMessage(sessionId, {
      messageId: assistantMsgId,
      sessionId,
      role: 'assistant',
      contentType: 'text',
      content: '',
      timestamp: Date.now(),
      status: 'streaming',
    });

    // 通过 HTTP POST 发送聊天请求
    const traceId = systemStore.currentTraceID || `web-${generateId()}`;
    fetch(`${this.backendUrl}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': traceId,
      },
      body: JSON.stringify({
        sessionId,
        message,
        msgId: assistantMsgId,
      }),
    }).then((resp) => {
      if (!resp.ok) {
        systemStore.addSystemLog(`发送聊天消息失败: ${resp.status}`);
        // 关键修复：HTTP 失败时必须将用户和 assistant 消息都标记为 error，
        // 确保 isWaiting 锁被正确释放
        sessionStore.updateMessageStatus(sessionId, userMsgId, 'error');
        sessionStore.updateMessageStatus(sessionId, assistantMsgId, 'error');
      } else {
        // HTTP 返回 200（表示后端已接收），用户消息变为 completed
        sessionStore.updateMessageStatus(sessionId, userMsgId, 'completed');
        // assistant 消息保持 streaming，isWaiting 维持为 true
      }
    }).catch((err) => {
      systemStore.addSystemLog(`发送聊天消息失败: ${err}`);
      // 关键修复：网络异常时必须将用户和 assistant 消息都标记为 error，
      // 否则 isWaiting 永久为 true
      sessionStore.updateMessageStatus(sessionId, userMsgId, 'error');
      sessionStore.updateMessageStatus(sessionId, assistantMsgId, 'error');
    });
  }

  /**
   * 获取日历元数据（通过 HTTP GET 调用）
   * 失败时自动关闭 loading 状态，防止 UI 卡死
   */
  public async fetchCalendarMetadata(yearMonth: string): Promise<void> {
    const systemStore = useSystemStore.getState();
    const traceId = systemStore.currentTraceID || `web-${generateId()}`;
    try {
      const resp = await fetch(`${this.backendUrl}/api/calendar?year_month=${encodeURIComponent(yearMonth)}`, {
        method: 'GET',
        headers: { 'X-Trace-ID': traceId },
      });
      if (resp.ok) {
        const data = await resp.json();
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setCalendarMetadata(
          data.payload.year_month,
          data.payload.active_dates || [],
        );
      } else {
        // 非 200 响应也要关闭 loading
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setCalendarMetadata(yearMonth, []);
        systemStore.addSystemLog(`获取日历元数据失败: HTTP ${resp.status}`);
      }
    } catch (err) {
      systemStore.addSystemLog(`获取日历元数据失败: ${err}`);
      // 请求失败时必须关闭 loading 状态，否则 UI 永久卡死
      const { useHistoryStore } = await import('../stores/historyStore');
      useHistoryStore.getState().setCalendarMetadata(yearMonth, []);
    }
  }

  /**
   * 获取指定日期聊天记录（通过 HTTP GET 调用）
   * 失败时自动关闭 loading 状态，防止 UI 卡死
   */
  public async fetchChatHistory(date: string): Promise<void> {
    const systemStore = useSystemStore.getState();
    const traceId = systemStore.currentTraceID || `web-${generateId()}`;
    try {
      const resp = await fetch(`${this.backendUrl}/api/chat_history?date=${encodeURIComponent(date)}`, {
        method: 'GET',
        headers: { 'X-Trace-ID': traceId },
      });
      if (resp.ok) {
        const data = await resp.json();
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setChatHistory(
          data.payload.date,
          data.payload.messages || [],
        );
      } else {
        // 非 200 响应也要关闭 loading
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setChatHistory(date, []);
        systemStore.addSystemLog(`获取聊天记录失败: HTTP ${resp.status}`);
      }
    } catch (err) {
      systemStore.addSystemLog(`获取聊天记录失败: ${err}`);
      // 请求失败时必须关闭 loading 状态，否则 UI 永久卡死
      const { useHistoryStore } = await import('../stores/historyStore');
      useHistoryStore.getState().setChatHistory(date, []);
    }
  }

  /**
   * 发送 Ping 请求（通过 HTTP GET 调用 health 端点）
   */
  public async sendPing(): Promise<void> {
    const systemStore = useSystemStore.getState();
    try {
      const resp = await fetch(`${this.backendUrl}/health`, {
        method: 'GET',
      });
      if (resp.ok) {
        systemStore.addSystemLog('Pong: AI 服务健康');
        systemStore.setAiConnectionStatus('connected');
      }
    } catch (err) {
      systemStore.addSystemLog(`Ping 失败: ${err}`);
    }
  }

  /**
   * 获取当前连接状态
   */
  public isConnected(): boolean {
    return this.eventSource !== null && this.eventSource.readyState === EventSource.OPEN;
  }

  /**
   * 断开 SSE 连接
   */
  public disconnect(): void {
    this.isManualDisconnect = true;
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    useSystemStore.getState().setConnectionStatus('disconnected');
    useSystemStore.getState().addSystemLog('SSE 已主动断开');
  }
}

// 导出单例实例
export const sseManager = new SSEManager();
