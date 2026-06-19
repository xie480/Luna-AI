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
  ChatStatusPayload,
  ChatStreamPayload,
  ChatUnifiedResponsePayload,
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
 * 待提交的近期记忆批次。
 * 做什么：按 assistant 回复批次聚合用户问题、assistant 内容与提交状态。
 * 为什么这样做：近期记忆提交必须以"单轮回答批次"为单位，而不能依赖全局气泡是否全部完成。
 */
interface PendingRecentMemoryEntry {
  batchId: string;
  userMsgId: string;
  userMessage: string;
  assistantContent: string;
  hasBubbleContent: boolean;
  streamFinished: boolean;
  committed: boolean;
  createdAt: number;
}

interface BubbleBatchSettledEventDetail {
  batchId: string;
  reason: string;
}

const BUBBLE_EVENT_NAME = {
  SHOW: 'luna:show-bubble',
  STREAM_FINISHED: 'luna:bubble-stream-finished',
  BATCH_SETTLED: 'luna:bubble-batch-settled',
  RECENT_MEMORY_COMMITTED: 'luna:recent-memory-committed',
} as const;

/**
 * SSE 管理器类
 * 替代原有的 WSManager，使用 EventSource + fetch 实现通信。
 */
class SSEManager {
  private eventSource: EventSource | null = null;
  private backendUrl: string = AI_SERVICE_BASE_URL;
  private isManualDisconnect: boolean = false;

  // 待提交近期记忆改为按 batchId 管理
  private pendingRecentMemoryMap: Map<string, PendingRecentMemoryEntry> = new Map();
  private isBubbleBatchSettledListenerRegistered: boolean = false;

  /**
   * 创建或覆盖一条待提交近期记忆记录。
   */
  private createPendingRecentMemory(batchId: string, userMsgId: string, userMessage: string): void {
    this.pendingRecentMemoryMap.set(batchId, {
      batchId,
      userMsgId,
      userMessage,
      assistantContent: '',
      hasBubbleContent: false,
      streamFinished: false,
      committed: false,
      createdAt: Date.now(),
    });
  }

  /**
   * 立即提交指定批次的近期记忆。
   */
  private flushPendingRecentMemory(batchId: string, reason: string): void {
    const entry = this.pendingRecentMemoryMap.get(batchId);
    if (!entry || entry.committed || !entry.userMsgId || !entry.userMessage.trim()) {
      return;
    }

    const newQA: InteractionQA = {
      msgId: entry.userMsgId,
      userContent: entry.userMessage,
      assistantContent: entry.assistantContent,
      timestamp: Math.floor(Date.now() / 1000),
    };
    useSessionStore.getState().addRecentQA(newQA);

    entry.committed = true;
    window.dispatchEvent(
      new CustomEvent(BUBBLE_EVENT_NAME.RECENT_MEMORY_COMMITTED, {
        detail: {
          batchId,
          msgId: entry.userMsgId,
          reason,
        },
      })
    );
    this.pendingRecentMemoryMap.delete(batchId);
  }

  /**
   * 注册批次沉降监听。
   */
  private registerBubbleBatchSettledListener(): void {
    if (this.isBubbleBatchSettledListenerRegistered) return;
    this.isBubbleBatchSettledListenerRegistered = true;

    window.addEventListener(BUBBLE_EVENT_NAME.BATCH_SETTLED, (event) => {
      const customEvent = event as CustomEvent<BubbleBatchSettledEventDetail>;
      const batchId = customEvent.detail?.batchId;
      if (!batchId) {
        return;
      }
      this.flushPendingRecentMemory(batchId, customEvent.detail?.reason || 'bubble-batch-settled');
    });
  }

  /**
   * 注册结构化 SSE 事件监听。
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
   */
  private asRecord(value: unknown): Record<string, unknown> | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return null;
    }
    return value as Record<string, unknown>;
  }

  private asString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined;
  }

  private asNumber(value: unknown): number | undefined {
    return typeof value === 'number' ? value : undefined;
  }

  private asBoolean(value: unknown): boolean | undefined {
    return typeof value === 'boolean' ? value : undefined;
  }

  /**
   * 解析 Phase 8.5 Chat Workflow 事件信封。
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
   */
  public connect(port: number = AI_SERVICE_PORT): void {
    this.backendUrl = `http://127.0.0.1:${port}`;
    this.isManualDisconnect = true;
    this.disconnect();
    this.isManualDisconnect = false;

    useSystemStore.getState().setConnectionStatus('connecting');

    try {
      this.eventSource = new EventSource(`${this.backendUrl}/sse/notifications`);
      this.setupEventHandlers();
    } catch (err) {
      const errMsg = `SSE 连接失败: ${err}`;
      useSystemStore.getState().addSystemLog(errMsg);
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
      // Phase 13：重连后同步鉴权队列，防止"状态撕裂"
      this.syncPendingAuths();
    });

    this.eventSource.onopen = () => {
      useSystemStore.getState().setConnectionStatus('connected');
      useSystemStore.getState().addSystemLog('SSE 已连接 (onopen)');
      this.syncInitState();
      // Phase 13：重连后同步鉴权队列
      this.syncPendingAuths();
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
    // EVT_CHAT_STATUS — Chat 状态通知（来自 ChatStatusPublisher）
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_CHAT_STATUS);
    // === Phase 13：Gating 鉴权事件（Python AI Service -> Electron） ===
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_TOOL_AUTH_REQUIRED);
    this.registerStructuredEventListener(WS_MSG_TYPE.EVT_PENDING_AUTHS_SYNC);

    // 通用消息事件（兜底处理所有未注册的事件类型）
    this.eventSource.onmessage = (event) => {
      try {
        const sseEvent: SSEEvent = JSON.parse(event.data);
        if (sseEvent.type === 'HEARTBEAT') return;
        if (sseEvent.type === 'CHAT_STREAM') return;

        const msg: WSMessage = {
          type: sseEvent.type as WSMsgType,
          trace_id: sseEvent.trace_id,
          payload: sseEvent.payload,
        };
        this.handleMessage(msg);
      } catch (err) {
        const errMsg = `解析 SSE 消息失败: ${err}`;
        useSystemStore.getState().addSystemLog(errMsg);
        createErrorToast('ERROR', 'SSE', errMsg);
        reportError('sse', errMsg).catch(() => {});
      }
    };

    // 错误处理
    this.eventSource.onerror = () => {
      useSystemStore.getState().addSystemLog('SSE 连接错误');
      useSystemStore.getState().setConnectionStatus('disconnected');
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
          // Phase 12: MCP 节点完成事件同时转发给 MCP 处理器
          if (event.payload.nodeType === ('mcp_tool_execution' as ChatWorkflowNodeType)) {
            import('./mcpSseHandlers').then(({ handleMCPNodeCompletedEvent }) => {
              handleMCPNodeCompletedEvent(event!.payload);
            });
          }
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
          // Phase 12: MCP 条件评估事件同时转发给 MCP 处理器
          if (
            event.payload.routeName === 'enter_mcp_tool' ||
            event.payload.routeName === 'bypass_mcp_tool'
          ) {
            import('./mcpSseHandlers').then(({ handleMCPConditionEvaluatedEvent }) => {
              handleMCPConditionEvaluatedEvent(event!.payload);
            });
          }
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

      case WS_MSG_TYPE.EVT_CHAT_STATUS: {
        const statusPayload = msg.payload as {
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
        };
        import('../stores/visualStatusQueueStore').then(({ useVisualStatusQueue }) => {
          useVisualStatusQueue.getState().onChatStatus(statusPayload);
        });
        // Phase 12: MCP 工具执行阶段事件同时转发给 MCP 处理器
        if (statusPayload.stage === 'mcp_tool_execution') {
          import('./mcpSseHandlers').then(({ handleMCPToolStatusEvent }) => {
            handleMCPToolStatusEvent(statusPayload as ChatStatusPayload);
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
        if (replyPayload.chunk && replyPayload.chunk.trim() && systemStore.showBubbleRender) {
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
          useHistoryStore.getState().setChatHistory(historyPayload.date, historyPayload.messages as any); // eslint-disable-line @typescript-eslint/no-explicit-any
          });
          break;
        }
  
        // ============================================================
        // Phase 13：权限治理与前端 Gating 事件处理
        // ============================================================
  
        case WS_MSG_TYPE.EVT_TOOL_AUTH_REQUIRED: {
          import('./mcpSseHandlers').then(({ handleToolAuthRequired }) => {
            handleToolAuthRequired({
              trace_id: msg.trace_id,
              task_id: '',
              timestamp: Date.now(),
              payload: msg.payload,
            });
          });
          break;
        }
  
        case WS_MSG_TYPE.EVT_PENDING_AUTHS_SYNC: {
          import('./mcpSseHandlers').then(({ handlePendingAuthsSync }) => {
            handlePendingAuthsSync(msg.payload as import('../../shared/types').PendingAuthsSyncPayload);
          });
          break;
        }
  
        default:
          systemStore.addSystemLog(`收到未知消息类型: ${msg.type}`);
    }
  }

  /**
   * 处理聊天流式输出（通过 SSE 接收的 ChatStreamPayload）。
   *
   * 做什么：根据 payload.type 分流到不同的处理路径——
   *   - unified_response：新协议，委托给 unifiedResponseHandler 处理整个回复包
   *   - reply_chunk / emotion_update 等：旧协议，沿用既有流式气泡渲染逻辑
   * 为什么这样做：过渡期需要同时兼容新旧两种协议，通过类型标识自动分流。
   */
  private handleChatStream(payload: ChatStreamPayload): void {
    // ---- 新协议分流：统一响应包 ----
    const rawType = (payload as ChatStreamPayload & { type?: string }).type;
    if (rawType === 'unified_response') {
      this.handleUnifiedResponseStream(payload as unknown as ChatUnifiedResponsePayload);
      return;
    }

    const systemStore = useSystemStore.getState();
    const sessionStore = useSessionStore.getState();
    const currentSessionId = sessionStore.currentSessionId;
    const assistantMessageId = payload.assistant_message_id || payload.node_id;
    const msgType = rawType || 'reply_chunk';
    const recentMemoryEntry = this.pendingRecentMemoryMap.get(assistantMessageId);

    // ---- 第一步：处理所有消息类型共有的内容更新 ----
    if (msgType === 'emotion_update') {
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
      const normalizedChunk = payload.chunk || '';
      const hasRenderableChunk = normalizedChunk.trim().length > 0;

      if (hasRenderableChunk) {
        // 如果后端传来了完整的断句以及可选的 TTS 音频地址，进入 playback 队列处理
        if (payload.is_sentence_chunk) {
          import('../stores/playbackStore').then(({ usePlaybackStore }) => {
            usePlaybackStore.getState().enqueue({
              text: normalizedChunk,
              audioUri: payload.audio_uri || null,
              batchId: assistantMessageId
            });
          });
        } else if (systemStore.showBubbleRender) {
          // 仅当气泡渲染开启时，旧逻辑才直接发送气泡展示事件
          const duration = Math.max(3000, normalizedChunk.length * 200);
          window.dispatchEvent(
            new CustomEvent(BUBBLE_EVENT_NAME.SHOW, {
              detail: { text: normalizedChunk, duration, batchId: assistantMessageId },
            })
          );
        }
      }

      if (currentSessionId) {
        sessionStore.updateMessageChunk(currentSessionId, assistantMessageId, normalizedChunk);
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

      if (recentMemoryEntry) {
        recentMemoryEntry.assistantContent += normalizedChunk;
        recentMemoryEntry.hasBubbleContent = recentMemoryEntry.hasBubbleContent || hasRenderableChunk;
      }
    }

    // ---- 第二步：统一处理所有消息类型的完成标记 ----
    if (payload.is_finished) {
      const status = payload.error ? 'error' : 'completed';
      if (currentSessionId) {
        sessionStore.updateMessageStatus(currentSessionId, assistantMessageId, status);
      }

      if (payload.error) {
        const errMsg = `生成失败: ${payload.error}`;
        systemStore.addSystemLog(errMsg);
        window.dispatchEvent(new CustomEvent('luna:notification', {
          detail: { message: errMsg, type: 'error', source: 'chat_stream' }
        }));
      }

      sessionStore.clearAllWaitingStates();

      if (recentMemoryEntry) {
        recentMemoryEntry.streamFinished = true;

        if (!recentMemoryEntry.hasBubbleContent) {
          this.flushPendingRecentMemory(assistantMessageId, 'stream-finished-without-bubbles');
        } else {
          // 气泡渲染关闭时，BATCH_SETTLED 事件永远不会触发（useBubble hook 不活跃），
          // 因此直接提交近期记忆，避免只有用户输入无 Luna 输出的问题。
          const showBubbleRender = useSystemStore.getState().showBubbleRender;
          if (!showBubbleRender) {
            this.flushPendingRecentMemory(assistantMessageId, 'stream-finished-no-bubbles');
          } else {
            window.dispatchEvent(
              new CustomEvent(BUBBLE_EVENT_NAME.STREAM_FINISHED, {
                detail: {
                  batchId: assistantMessageId,
                  finishedAt: Date.now(),
                },
              })
            );
          }
        }
      }

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
   * 处理统一响应流（新协议 unified_response）。
   *
   * 做什么：接收后端一次合成的完整回复包，执行两个维度的处理——
   *   1. 状态维度：更新 sessionStore 消息内容、元数据、状态
   *   2. 渲染维度：委托 unifiedResponseHandler 驱动 Live2D 表情、气泡队列、TTS 音频
   * 为什么这样做：统一响应是一次性完整数据，不需要流式逐字拼接，
   *             但仍然需要正确更新 Store 中的消息状态和近期记忆。
   * 输入输出：输入 ChatUnifiedResponsePayload，输出为 Store 更新与 UI 副作用。
   * 边界条件：
   *   - reply_text 为空时只更新状态不渲染气泡
   *   - error 非空时标记消息为 error 状态
   * 异常行为：无。
   */
  private handleUnifiedResponseStream(payload: ChatUnifiedResponsePayload): void {
    const systemStore = useSystemStore.getState();
    const sessionStore = useSessionStore.getState();
    const currentSessionId = sessionStore.currentSessionId;
    const assistantMessageId = payload.assistant_message_id;
    const recentMemoryEntry = this.pendingRecentMemoryMap.get(assistantMessageId);

    // ---- 判断是否跳过持久化（如 MCP Evaluation reply） ----
    // 当 skip_persistence=true 时，跳过聊天记录、近期记忆的写入，
    // 仅执行 UI 渲染（Live2D 表情、气泡、TTS 音频）。
    const skipPersistence = payload.skip_persistence === true;

    if (!skipPersistence) {
      // ---- 更新 sessionStore：完整回复文本 ----
      if (currentSessionId) {
        sessionStore.updateMessageChunk(currentSessionId, assistantMessageId, payload.reply_text);

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
        if (payload.citations) {
          streamMetadata.citations = payload.citations;
        }
        if (payload.e2e_latency_ms !== undefined) {
          streamMetadata.e2eLatencyMs = payload.e2e_latency_ms;
        }
        if (Object.keys(streamMetadata).length > 0) {
          sessionStore.updateMessageMetadata(currentSessionId, assistantMessageId, streamMetadata);
        }
      }

      // ---- 更新近期记忆内容 ----
      if (recentMemoryEntry) {
        recentMemoryEntry.assistantContent += payload.reply_text;
        recentMemoryEntry.hasBubbleContent =
          recentMemoryEntry.hasBubbleContent || payload.reply_text.trim().length > 0;
      }

      // ---- 标记消息完成 ----
      const status = payload.error ? 'error' : 'completed';
      if (currentSessionId) {
        sessionStore.updateMessageStatus(currentSessionId, assistantMessageId, status);
      }

      if (payload.error) {
        const errMsg = `生成失败: ${payload.error}`;
        systemStore.addSystemLog(errMsg);
        window.dispatchEvent(
          new CustomEvent('luna:notification', {
            detail: { message: errMsg, type: 'error', source: 'unified_response' },
          }),
        );
      }

      sessionStore.clearAllWaitingStates();

      // ---- 近期记忆提交 ----
      if (recentMemoryEntry) {
        recentMemoryEntry.streamFinished = true;

        if (!recentMemoryEntry.hasBubbleContent) {
          this.flushPendingRecentMemory(assistantMessageId, 'unified-finished-without-bubbles');
        } else {
          // 气泡渲染关闭时，BATCH_SETTLED 事件永远不会触发（useBubble hook 不活跃），
          // 因此直接提交近期记忆，避免只有用户输入无 Luna 输出的问题。
          const showBubbleRender = useSystemStore.getState().showBubbleRender;
          if (!showBubbleRender) {
            this.flushPendingRecentMemory(assistantMessageId, 'unified-finished-no-bubbles');
          } else {
            window.dispatchEvent(
              new CustomEvent(BUBBLE_EVENT_NAME.STREAM_FINISHED, {
                detail: {
                  batchId: assistantMessageId,
                  finishedAt: Date.now(),
                },
              }),
            );
          }
        }
      }

      // ---- 日历记录更新 ----
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

    // ---- 委托 UI 渲染：Live2D 表情 + 语义切分 + 气泡队列 + TTS 音频 ----
    // 无论 skipPersistence 为何值，UI 渲染都必须执行。
    import('./unifiedResponseHandler').then(({ handleUnifiedResponse }) => {
      handleUnifiedResponse(payload);
    });
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
        if (data.payload) {
          this.handleInitState(data.payload as InitStatePayload);
        }
      }
    } catch (err) {
      useSystemStore.getState().addSystemLog(`初始化状态同步失败: ${err}`);
    }
  }

  /**
   * 同步当前 PENDING_APPROVAL 状态的鉴权请求列表（Phase 13）。
   *
   * 做什么：断线重连后，向后端请求当前所有有效的 PENDING_APPROVAL 鉴权请求。
   *         后端返回后，SSE 推送 EVT_PENDING_AUTHS_SYNC 事件，
   *         handleMessage 中的对应 case 会清洗旧队列并重建。
   * 为什么这样做：防止断线后后端的审批状态已变更，前端的陈旧卡片导致"状态撕裂"。
   *             一刀切快照刷新是最可靠的恢复策略。
   * 输入输出：发送 CMD_SYNC_PENDING_AUTHS 到后端。
   * 边界条件：网络异常时静默降级，不影响主流程。
   * 异常行为：无。
   */
  private async syncPendingAuths(): Promise<void> {
    const traceId = `web-${generateId()}`;
    try {
      const resp = await fetch(`${this.backendUrl}/api/gating/sync_init_state`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-ID': traceId,
        },
        body: JSON.stringify({
          force: true
        }),
      });
      if (!resp.ok) {
        useSystemStore.getState().addSystemLog(`同步鉴权请求列表失败: HTTP ${resp.status}`);
      }
    } catch (err) {
      useSystemStore.getState().addSystemLog(`同步鉴权请求列表异常: ${err}`);
    }
  }

  /**
   * 发送用户聊天消息（通过 HTTP POST 调用）
   */
  public sendChatMessage(message: string): void {
    const sessionStore = useSessionStore.getState();
    const systemStore = useSystemStore.getState();
    const sessionId = sessionStore.currentSessionId;

    if (!sessionId) {
      systemStore.addSystemLog('无活跃会话，无法发送消息');
      return;
    }

    this.registerBubbleBatchSettledListener();

    const userMsgId = generateId();
    const assistantMsgId = generateId();
    this.createPendingRecentMemory(assistantMsgId, userMsgId, message);

    sessionStore.appendMessage(sessionId, {
      messageId: userMsgId,
      sessionId,
      role: 'user',
      contentType: 'text',
      content: message,
      timestamp: Date.now(),
      status: 'sending',
    });

    sessionStore.appendMessage(sessionId, {
      messageId: assistantMsgId,
      sessionId,
      role: 'assistant',
      contentType: 'text',
      content: '',
      timestamp: Date.now(),
      status: 'streaming',
    });

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
        ttsEnabled: systemStore.isTTSEnabled,
        // TTS 语音语言选项：zh（中文）/ ja（日语）
        ttsLanguage: systemStore.ttsLanguage,
        // LLM 响应模式：unified（统一非流式，默认）/ streaming（传统流式兼容）
        llmResponseMode: systemStore.llmResponseMode ?? 'unified',
        // 聊天模式：daily_chat（深度日常助理）/ casual_chat（极速闲聊）
        chatMode: systemStore.chatMode,
      }),
    }).then((resp) => {
      if (!resp.ok) {
        systemStore.addSystemLog(`发送聊天消息失败: ${resp.status}`);
        sessionStore.updateMessageStatus(sessionId, userMsgId, 'error');
        sessionStore.updateMessageStatus(sessionId, assistantMsgId, 'error');
        this.flushPendingRecentMemory(assistantMsgId, 'http-request-failed');
      } else {
        sessionStore.updateMessageStatus(sessionId, userMsgId, 'completed');
      }
    }).catch((err) => {
      systemStore.addSystemLog(`发送聊天消息失败: ${err}`);
      sessionStore.updateMessageStatus(sessionId, userMsgId, 'error');
      sessionStore.updateMessageStatus(sessionId, assistantMsgId, 'error');
      this.flushPendingRecentMemory(assistantMsgId, 'http-request-exception');
    });
  }

  /**
   * 获取日历元数据
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
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setCalendarMetadata(yearMonth, []);
        systemStore.addSystemLog(`获取日历元数据失败: HTTP ${resp.status}`);
      }
    } catch (err) {
      systemStore.addSystemLog(`获取日历元数据失败: ${err}`);
      const { useHistoryStore } = await import('../stores/historyStore');
      useHistoryStore.getState().setCalendarMetadata(yearMonth, []);
    }
  }

  /**
   * 获取指定日期聊天记录
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
          (data.payload.messages as any) || [],
        );
      } else {
        const { useHistoryStore } = await import('../stores/historyStore');
        useHistoryStore.getState().setChatHistory(date, []);
        systemStore.addSystemLog(`获取聊天记录失败: HTTP ${resp.status}`);
      }
    } catch (err) {
      systemStore.addSystemLog(`获取聊天记录失败: ${err}`);
      const { useHistoryStore } = await import('../stores/historyStore');
      useHistoryStore.getState().setChatHistory(date, []);
    }
  }

  /**
   * 发送 Ping 请求
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
