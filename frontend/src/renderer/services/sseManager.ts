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
import { useChatWorkflowStore } from '../stores/chatWorkflowStore';
import { EMOTION_EXPRESSIONS } from '../constants/emotionExpressions';
import { CHAT_PLAN_PRESET, CHAT_WORKFLOW_SCHEMA_VERSION, WS_MSG_TYPE, WSMsgType } from '../../shared/enum';
import { generateId } from '../../shared/utils/snowflake';
import { createErrorToast } from '../stores/errorToastStore';
import { reportError } from '../services/errorLogService';
import {
  WSMessage,
  PongPayload,
  ErrorPayload,
  ChatConditionEvaluatedPayload,
  ChatNodeStatusPayload,
  ChatPlanLifecyclePayload,
  ChatPostprocessPayload,
  ChatStreamPayload,
  ChatWorkflowEventEnvelope,
  ChatWorkflowNodeType,
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
   * 注册结构化 SSE 事件监听。
   * 做什么：统一解析后端以命名事件形式推送的结构化消息并转交给 [`handleMessage()`](frontend/src/renderer/services/sseManager.ts:235)。
   * 为什么这样做：Phase 8.5 新增了多种 workflow 事件，若继续逐个复制监听代码，容易出现漏接和解析逻辑漂移。
   * 输入输出：输入事件名，输出为内部消息分发副作用。
   * 边界条件：`eventSource` 未初始化时直接返回。
   * 异常行为：解析失败时会写系统日志并上报错误提示，不伪造成功。
   */
  private registerStructuredEventListener(eventName: string): void {
    if (!this.eventSource) return;
    this.eventSource.addEventListener(eventName, (event) => {
      try {
        const sseEvent: SSEEvent = JSON.parse(event.data);
        const msg: WSMessage = {
          type: sseEvent.type as WSMsgType,
          trace_id: sseEvent.trace_id,
          payload: sseEvent.payload,
        };
        this.handleMessage(msg);
      } catch (err) {
        const errMsg = `解析 ${eventName} 消息失败: ${err}`;
        useSystemStore.getState().addSystemLog(errMsg);
        createErrorToast('ERROR', 'SSE', errMsg);
        reportError('sse', errMsg).catch(() => {});
      }
    });
  }

  /**
   * 把未知值缩小为记录对象。
   * 做什么：为 workflow 事件 envelope 做最小结构校验。
   * 为什么这样做：SSE payload 来自跨层通信，前端禁止假设输入一定合法。
   * 输入输出：输入未知值，输出对象记录或 null。
   * 边界条件：数组与 null 都视为非法对象。
   * 异常行为：无。
   */
  private asRecord(value: unknown): Record<string, unknown> | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return null;
    }
    return value as Record<string, unknown>;
  }

  /** 读取字符串字段。 */
  private asString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined;
  }

  /** 读取数字字段。 */
  private asNumber(value: unknown): number | undefined {
    return typeof value === 'number' ? value : undefined;
  }

  /** 读取布尔字段。 */
  private asBoolean(value: unknown): boolean | undefined {
    return typeof value === 'boolean' ? value : undefined;
  }

  /**
   * 解析 Phase 8.5 Chat Workflow 事件信封。
   * 做什么：把后端 snake_case envelope 转为前端 camelCase 强类型结构。
   * 为什么这样做：Store 和组件层统一使用 camelCase，避免在消费层反复解析原始对象。
   * 输入输出：输入后端原始 payload 与内部 payload 映射器，输出强类型事件或 null。
   * 边界条件：核心字段缺失时直接返回 null，不进入业务 Store。
   * 异常行为：无。
   */
  private mapWorkflowEventEnvelope<TPayload>(
    rawPayload: unknown,
    mapPayload: (payload: Record<string, unknown>) => TPayload
  ): ChatWorkflowEventEnvelope<TPayload> | null {
    const envelope = this.asRecord(rawPayload);
    const nestedPayload = this.asRecord(envelope?.payload);
    const eventId = this.asString(envelope?.event_id);
    const eventType = this.asString(envelope?.event_type);
    const traceId = this.asString(envelope?.trace_id);
    const interactionId = this.asString(envelope?.interaction_id);
    const sessionId = this.asString(envelope?.session_id);
    const timestampMs = this.asNumber(envelope?.timestamp_ms);
    if (
      !envelope ||
      !nestedPayload ||
      !eventId ||
      !eventType ||
      !traceId ||
      !interactionId ||
      !sessionId ||
      timestampMs === undefined
    ) {
      useSystemStore.getState().addSystemLog('收到非法 Chat Workflow 事件，已忽略');
      return null;
    }
    return {
      schemaVersion: CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1,
      eventId,
      eventType: eventType as ChatWorkflowEventEnvelope<TPayload>['eventType'],
      traceId,
      interactionId,
      sessionId,
      planPresetId: CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT,
      nodeType: this.asString(envelope.node_type) as ChatWorkflowNodeType | undefined,
      timestampMs,
      payload: mapPayload(nestedPayload),
    };
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
      } catch (e) {
        // ignore JSON parse error
      }

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

    // 结构化业务事件
    this.registerStructuredEventListener(WS_MSG_TYPE.CHAT_STREAM);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_INIT_STATE);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_STREAM_CHUNK);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_PLAN_STARTED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_NODE_STARTED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_NODE_COMPLETED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_NODE_FAILED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_NODE_DEGRADED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_CONDITION_EVALUATED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_STARTED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_COMPLETED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_PLAN_COMPLETED);

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

      case WS_MSG_TYPE.CHAT_STREAM:
      case WS_MSG_TYPE.EVT_CHAT_STREAM_CHUNK: {
        const chatPayload = msg.payload as ChatStreamPayload;
        this.handleChatStream(chatPayload);
        break;
      }

      case WS_MSG_TYPE.EVT_CHAT_PLAN_STARTED: {
        const workflowStore = useChatWorkflowStore.getState();
        const event = this.mapWorkflowEventEnvelope(msg.payload, (payload): ChatPlanLifecyclePayload => ({
          nodeObservationCount: this.asNumber(payload.node_observation_count) ?? 0,
          assistantMessageId: this.asString(payload.assistant_message_id) ?? '',
        }));
        if (event && event.payload.assistantMessageId) {
          workflowStore.onPlanStarted(event);
          sessionStore.updateMessageMetadata(event.sessionId, event.payload.assistantMessageId, {
            schemaVersion: event.schemaVersion,
            traceId: event.traceId,
            interactionId: event.interactionId,
            assistantMessageId: event.payload.assistantMessageId,
            planPresetId: event.planPresetId,
          });
        }
        break;
      }

      case WS_MSG_TYPE.EVT_CHAT_NODE_STARTED:
      case WS_MSG_TYPE.EVT_CHAT_NODE_COMPLETED:
      case WS_MSG_TYPE.EVT_CHAT_NODE_FAILED:
      case WS_MSG_TYPE.EVT_CHAT_NODE_DEGRADED: {
        const workflowStore = useChatWorkflowStore.getState();
        const event = this.mapWorkflowEventEnvelope(msg.payload, (payload): ChatNodeStatusPayload => ({
          nodeType: (this.asString(payload.node_type) ?? '') as ChatWorkflowNodeType,
          status: (this.asString(payload.status) ?? '') as ChatNodeStatusPayload['status'],
          startedAtMs: this.asNumber(payload.started_at_ms),
          endedAtMs: this.asNumber(payload.ended_at_ms),
          latencyMs: this.asNumber(payload.latency_ms),
          degradedReason: this.asString(payload.degraded_reason),
          errorCode: this.asString(payload.error_code),
        }));
        if (event && event.payload.nodeType && event.payload.status) {
          workflowStore.onNodeStatus(event);
        }
        break;
      }

      case WS_MSG_TYPE.EVT_CHAT_CONDITION_EVALUATED: {
        const workflowStore = useChatWorkflowStore.getState();
        const event = this.mapWorkflowEventEnvelope(msg.payload, (payload): ChatConditionEvaluatedPayload => ({
          sourceNodeType: (this.asString(payload.source_node_type) ?? '') as ChatWorkflowNodeType,
          targetNodeType: (this.asString(payload.target_node_type) ?? '') as ChatWorkflowNodeType,
          conditionEntered: this.asBoolean(payload.condition_entered) ?? false,
          routeName: this.asString(payload.route_name) ?? '',
          reason: this.asString(payload.reason) ?? '',
        }));
        if (event && event.payload.sourceNodeType && event.payload.targetNodeType && event.payload.routeName) {
          workflowStore.onConditionEvaluated(event);
        }
        break;
      }

      case WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_STARTED:
      case WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_COMPLETED: {
        const workflowStore = useChatWorkflowStore.getState();
        const event = this.mapWorkflowEventEnvelope(msg.payload, (payload): ChatPostprocessPayload => ({
          nodeObservationCount: this.asNumber(payload.node_observation_count) ?? 0,
          assistantMessageId: this.asString(payload.assistant_message_id) ?? '',
        }));
        if (event && event.payload.assistantMessageId) {
          workflowStore.onPostprocessStatus(
            event,
            msgType === WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_STARTED ? 'started' : 'completed'
          );
          sessionStore.updateMessageMetadata(event.sessionId, event.payload.assistantMessageId, {
            postprocessStatus: msgType === WS_MSG_TYPE.EVT_CHAT_POSTPROCESS_STARTED ? 'running' : 'completed',
          });
        }
        break;
      }

      case WS_MSG_TYPE.EVT_CHAT_PLAN_COMPLETED: {
        const workflowStore = useChatWorkflowStore.getState();
        const event = this.mapWorkflowEventEnvelope(msg.payload, (payload): ChatPlanLifecyclePayload => ({
          nodeObservationCount: this.asNumber(payload.node_observation_count) ?? 0,
          assistantMessageId: this.asString(payload.assistant_message_id) ?? '',
        }));
        if (event && event.payload.assistantMessageId) {
          workflowStore.onPlanCompleted(event);
          sessionStore.updateMessageMetadata(event.sessionId, event.payload.assistantMessageId, {
            workflowCompletedAt: event.timestampMs,
          });
        }
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

      case WS_MSG_TYPE.EVT_RAG_THOUGHT: {
        const thoughtPayload = msg.payload as Record<string, unknown>;
        const sessionStore = useSessionStore.getState();
        const sessionId = sessionStore.currentSessionId;
        if (sessionId) {
          const msgs = sessionStore.messages[sessionId] || [];
          const targetMsg = msgs.slice().reverse().find(m => m.role === 'assistant' && (m.status === 'streaming' || m.status === 'sending'));
          
          if (targetMsg) {
            const currentThoughts = (targetMsg.metadata?.thoughts as Record<string, unknown>[]) || [];
            sessionStore.updateMessageMetadata(sessionId, targetMsg.messageId, {
              thoughts: [...currentThoughts, thoughtPayload]
            });
          }
        }
        break;
      }

      case WS_MSG_TYPE.EVT_RAG_CITATION: {
        const citationPayload = msg.payload as { citations: unknown[] };
        const sessionStore = useSessionStore.getState();
        const sessionId = sessionStore.currentSessionId;
        if (sessionId) {
          const msgs = sessionStore.messages[sessionId] || [];
          const targetMsg = msgs.slice().reverse().find(m => m.role === 'assistant' && (m.status === 'streaming' || m.status === 'sending' || m.status === 'completed'));
          
          if (targetMsg) {
            sessionStore.updateMessageMetadata(sessionId, targetMsg.messageId, {
              citations: citationPayload.citations
            });
          }
        }
        break;
      }

      case WS_MSG_TYPE.EVT_PLAN_SNAPSHOT: {
        sessionStore.updatePlan(msg.payload as unknown as any); // eslint-disable-line @typescript-eslint/no-explicit-any
        break;
      }

      case WS_MSG_TYPE.EVT_NODE_STATUS_UPDATE: {
        const nodePayload = msg.payload as { nodeId: string; status: unknown; progress?: number };
        sessionStore.updateNodeStatus(nodePayload.nodeId, nodePayload.status as any, nodePayload.progress); // eslint-disable-line @typescript-eslint/no-explicit-any
        break;
      }

      case WS_MSG_TYPE.EVT_MEMORY_UPDATED: {
        sessionStore.updateMemory(msg.payload as unknown as any); // eslint-disable-line @typescript-eslint/no-explicit-any
        break;
      }

      case WS_MSG_TYPE.EVT_DEBUG_LOG: {
        const logPayload = msg.payload as { message?: string };
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
        const historyPayload = msg.payload as { date: string; messages: unknown[] };
        import('../stores/historyStore').then(({ useHistoryStore }) => {
          // @ts-expect-error type mismatches for now
          useHistoryStore.getState().setChatHistory(historyPayload.date, historyPayload.messages as any); // eslint-disable-line @typescript-eslint/no-explicit-any
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
    const assistantMessageId = payload.assistant_message_id || payload.node_id;
    const msgType = payload.type || 'reply_chunk';

    // ---- 第一步：处理所有消息类型共有的内容更新 ----
    if (msgType === 'emotion_update') {
      // 情绪更新：不涉及内容拼接，仅更新状态和触发事件
      const rawEmotion = payload.chunk as string;
      const normalizedEmotion = rawEmotion ? rawEmotion.trim() : 'neutral';
      const validEmotions = ['neutral', ...Object.keys(EMOTION_EXPRESSIONS)] as const;
      const emotionValue = validEmotions.includes(normalizedEmotion as any) // eslint-disable-line @typescript-eslint/no-explicit-any
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
        sessionStore.updateMessageChunk(currentSessionId, assistantMessageId, payload.chunk);
        const streamMetadata: Record<string, unknown> = {};
        if (payload.schema_version) {
          streamMetadata.schemaVersion = payload.schema_version;
        }
        if (payload.interaction_id) {
          streamMetadata.interactionId = payload.interaction_id;
        }
        if (payload.assistant_message_id) {
          streamMetadata.assistantMessageId = payload.assistant_message_id;
        }
        if (payload.plan_preset_id) {
          streamMetadata.planPresetId = payload.plan_preset_id;
        }
        if (payload.current_node_type) {
          streamMetadata.currentNodeType = payload.current_node_type;
        }
        if (payload.citations) {
          streamMetadata.citations = payload.citations;
        }
        if (Object.keys(streamMetadata).length > 0) {
          sessionStore.updateMessageMetadata(currentSessionId, assistantMessageId, streamMetadata);
        }
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
        sessionStore.updateMessageStatus(currentSessionId, assistantMessageId, status);
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

      // Ensure waiting lock is removed here immediately upon finished signal,
      // but memory insertion waits for bubbles
      sessionStore.clearAllWaitingStates();

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
          (data.payload.active_dates as string[]) || [],
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
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (data.payload.messages as any) || [],
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
