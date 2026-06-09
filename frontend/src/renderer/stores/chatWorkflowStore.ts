import { create } from 'zustand';
import {
  CHAT_MODE,
  CHAT_NODE_STATUS,
  CHAT_PLAN_PRESET,
  CHAT_WORKFLOW_NODE_LABEL,
  CHAT_WORKFLOW_NODE_TYPE,
  CHAT_WORKFLOW_SCHEMA_VERSION,
} from '../../shared/enum';
import type {
  ChatConditionEvaluatedPayload,
  ChatNodeStatusPayload,
  ChatPlanLifecyclePayload,
  ChatPostprocessPayload,
  ChatWorkflowEventEnvelope,
  ChatWorkflowNodeType,
} from '../../shared/types';
import type {
  ChatConditionResultMap,
  ChatNodeProjection,
  ChatPlanProjection,
  ChatWorkflowDebugEvent,
  ChatWorkflowDebugTimeline,
  ChatWorkflowMessageMetadata,
  ChatPlanStatus,
} from '../types/chatWorkflow';

/**
 * 调试时间线最近保留的最大事件数。
 * 做什么：限制单个 trace_id 在前端内存中的调试事件数量。
 * 为什么这样做：调试事件可能较多，必须限制体积避免无上限增长影响渲染性能。
 * 输入输出：无。
 * 边界条件：超过上限时仅保留最近事件。
 * 异常行为：无。
 */
const MAX_DEBUG_EVENTS_PER_TRACE = 200;

/**
 * 当前三个条件节点的目标类型集合。
 * 做什么：集中声明 Phase 8.5 需要特殊展示的条件节点。
 * 为什么这样做：元数据面板与步骤条只应读取后端明确给出的条件结果，不能在组件中散落节点判断。
 * 输入输出：无。
 * 边界条件：后续新增条件节点时必须同步扩展此常量。
 * 异常行为：无。
 */
const CONDITION_NODE_TYPES = new Set<ChatWorkflowNodeType>([
  CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG,
  CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION,
  CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG,
]);

/**
 * Store 状态结构。
 * 做什么：承载当前聊天主链路的 plan 投影、节点表、调试时间线与 UI 展示状态。
 * 为什么这样做：把低频 workflow 事件与高频流式文本状态解耦，避免主聊天区域无意义重渲染。
 * 输入输出：无。
 * 边界条件：当前仅支持单一活跃 plan，不支持多 plan 并发视图。
 * 异常行为：无。
 */
interface ChatWorkflowStoreState {
  activePlan: ChatPlanProjection | null;
  nodesByInteractionId: Record<string, ChatNodeProjection[]>;
  debugTimelineByTraceId: Record<string, ChatWorkflowDebugTimeline>;
  latestConditionResults: ChatConditionResultMap;
  isStepBarVisible: boolean;
  expandedNodeTypes: Record<string, boolean>;
  expandedConditionReasons: Record<string, boolean>;
  metadataPanelExpandedByMessageId: Record<string, boolean>;
  isWorkflowDebugDrawerOpen: boolean;
  isCitationPanelVisible: boolean;

  onPlanStarted: (event: ChatWorkflowEventEnvelope<ChatPlanLifecyclePayload>) => void;
  onNodeStatus: (event: ChatWorkflowEventEnvelope<ChatNodeStatusPayload>) => void;
  onConditionEvaluated: (event: ChatWorkflowEventEnvelope<ChatConditionEvaluatedPayload>) => void;
  onPostprocessStatus: (
    event: ChatWorkflowEventEnvelope<ChatPostprocessPayload>,
    status: 'started' | 'completed'
  ) => void;
  onPlanCompleted: (event: ChatWorkflowEventEnvelope<ChatPlanLifecyclePayload>) => void;
  clearInteraction: (interactionId: string) => void;
  clearAll: () => void;
  setStepBarVisible: (visible: boolean) => void;
  toggleNodeExpanded: (interactionId: string, nodeType: ChatWorkflowNodeType) => void;
  toggleConditionReasonExpanded: (interactionId: string, nodeType: ChatWorkflowNodeType) => void;
  toggleMetadataPanelExpanded: (messageId: string) => void;
  setWorkflowDebugDrawerOpen: (open: boolean) => void;
  setCitationPanelVisible: (visible: boolean) => void;
  getMessageMetadata: (
    interactionId: string | undefined,
    assistantMessageId: string | undefined
  ) => ChatWorkflowMessageMetadata | null;
}

/**
 * 生成 interaction + 节点类型的稳定键。
 * 做什么：为条件理由展开态和节点展开态构建索引键。
 * 为什么这样做：避免组件层拼接自由格式字符串导致状态命名漂移。
 * 输入输出：输入 interactionId 与 nodeType，输出稳定字符串键。
 * 边界条件：interactionId 为空时调用方应避免使用。
 * 异常行为：无。
 */
function buildNodeUiKey(interactionId: string, nodeType: ChatWorkflowNodeType): string {
  return `${interactionId}:${nodeType}`;
}

/**
 * 生成 interaction + 条件节点的结果索引键。
 * 做什么：统一管理条件判断结果索引。
 * 为什么这样做：同一 interaction 下多个条件节点必须以稳定键值保存。
 * 输入输出：输入 interactionId 与目标节点类型，输出条件结果键。
 * 边界条件：仅应对条件节点调用。
 * 异常行为：无。
 */
function buildConditionResultKey(interactionId: string, nodeType: ChatWorkflowNodeType): string {
  return `${interactionId}:${nodeType}`;
}

/**
 * 读取或创建指定 interaction 的节点投影列表。
 * 做什么：确保节点状态更新时总能拿到可变副本。
 * 为什么这样做：Zustand 需要不可变更新，但节点事件频率低，数组结构更适合 UI 顺序展示。
 * 输入输出：输入旧状态数组，输出浅拷贝数组。
 * 边界条件：interaction 首次出现时返回空数组。
 * 异常行为：无。
 */
function cloneNodeList(nodes: ChatNodeProjection[] | undefined): ChatNodeProjection[] {
  return nodes ? nodes.map((item) => ({ ...item })) : [];
}

/**
 * 写入或更新某个节点投影。
 * 做什么：在保持原有节点顺序的同时按 nodeType 合并最新字段。
 * 为什么这样做：后端事件顺序代表执行顺序，前端不应重排已有节点。
 * 输入输出：输入节点列表与更新对象，输出新的节点列表。
 * 边界条件：首次出现的节点会被追加到列表末尾。
 * 异常行为：无。
 */
function upsertNodeProjection(
  nodes: ChatNodeProjection[],
  nextNode: ChatNodeProjection
): ChatNodeProjection[] {
  const targetIndex = nodes.findIndex((item) => item.nodeType === nextNode.nodeType);
  if (targetIndex === -1) {
    return [...nodes, nextNode];
  }
  const updatedNodes = [...nodes];
  updatedNodes[targetIndex] = {
    ...updatedNodes[targetIndex],
    ...nextNode,
  };
  return updatedNodes;
}

/**
 * 根据节点列表统计计划状态。
 * 做什么：从后端已推送的节点状态中派生当前 plan 的展示状态。
 * 为什么这样做：Phase 8.5 只有单一 plan，前端仅需要轻量展示态，不参与真实调度裁决。
 * 输入输出：输入节点列表与是否在后处理中，输出展示用 plan 状态。
 * 边界条件：存在失败节点时优先标记 failed；处于后处理时标记 postprocessing。
 * 异常行为：无。
 */
function derivePlanStatus(nodes: ChatNodeProjection[], isPostprocessing: boolean): ChatPlanStatus {
  if (nodes.some((item) => item.status === CHAT_NODE_STATUS.FAILED)) {
    return 'failed';
  }
  if (isPostprocessing) {
    return 'postprocessing';
  }
  if (nodes.length > 0 && nodes.every((item) => item.status !== CHAT_NODE_STATUS.RUNNING)) {
    return 'completed';
  }
  return 'running';
}

/**
 * 构建调试事件摘要文案。
 * 做什么：把强类型 workflow 事件转换为调试时间线可读文本。
 * 为什么这样做：调试面板必须展示原因和状态，但不能让组件层重复拼装同类文案。
 * 输入输出：输入事件与标题，输出调试事件对象。
 * 边界条件：detail 应尽量简短，避免普通 UI 泄露过多内部细节。
 * 异常行为：无。
 */
function buildDebugEvent(
  title: string,
  detail: string,
  payloadSummary: string,
  event: {
    eventId: string;
    eventType: ChatWorkflowEventEnvelope<unknown>['eventType'];
    nodeType?: ChatWorkflowNodeType;
    timestampMs: number;
  }
): ChatWorkflowDebugEvent {
  return {
    eventId: event.eventId,
    eventType: event.eventType,
    nodeType: event.nodeType,
    timestampMs: event.timestampMs,
    title,
    detail,
    payloadSummary,
  };
}

/**
 * 安全裁剪调试时间线长度。
 * 做什么：限制单个 trace_id 仅保留最近固定数量事件。
 * 为什么这样做：避免长对话在调试态积累过量文本导致内存和渲染压力。
 * 输入输出：输入时间线事件数组，输出裁剪后的数组。
 * 边界条件：事件数量不超上限时原样返回。
 * 异常行为：无。
 */
function trimDebugEvents(events: ChatWorkflowDebugEvent[]): ChatWorkflowDebugEvent[] {
  if (events.length <= MAX_DEBUG_EVENTS_PER_TRACE) {
    return events;
  }
  return events.slice(events.length - MAX_DEBUG_EVENTS_PER_TRACE);
}

/**
 * 读取当前活跃节点类型。
 * 做什么：从节点列表中定位最后一个运行中的节点。
 * 为什么这样做：步骤条应显示后端最新运行节点，而不是前端猜测的下一步。
 * 输入输出：输入节点列表，输出当前运行节点类型或最近更新节点类型。
 * 边界条件：没有运行节点时退回到最后一个节点。
 * 异常行为：无。
 */
function resolveActiveNodeType(nodes: ChatNodeProjection[]): ChatWorkflowNodeType | undefined {
  const runningNode = [...nodes].reverse().find((item) => item.status === CHAT_NODE_STATUS.RUNNING);
  if (runningNode) {
    return runningNode.nodeType;
  }
  return nodes[nodes.length - 1]?.nodeType;
}

/**
 * 从条件结果中提取消息元数据所需布尔值。
 * 做什么：将条件节点进入结果映射到 assistant 消息元数据面板。
 * 为什么这样做：元数据面板只做展示，不应知道底层条件索引结构。
 * 输入输出：输入 interaction 条件结果映射，输出三个条件节点是否进入。
 * 边界条件：未收到条件事件时返回 undefined。
 * 异常行为：无。
 */
function resolveConditionBooleans(
  latestConditionResults: ChatConditionResultMap,
  interactionId: string
): Pick<
  ChatWorkflowMessageMetadata,
  'enteredLongTermMemoryRag' | 'enteredUserProfileInjection' | 'enteredKnowledgeRag'
> {
  const longTerm = latestConditionResults[
    buildConditionResultKey(interactionId, CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG)
  ];
  const profile = latestConditionResults[
    buildConditionResultKey(interactionId, CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION)
  ];
  const knowledge = latestConditionResults[
    buildConditionResultKey(interactionId, CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG)
  ];
  return {
    enteredLongTermMemoryRag: longTerm?.conditionEntered,
    enteredUserProfileInjection: profile?.conditionEntered,
    enteredKnowledgeRag: knowledge?.conditionEntered,
  };
}

/**
 * Chat Workflow Zustand Store。
 * 做什么：承接 Phase 8.5 新增的 workflow 事件，维护 plan、节点、条件与调试投影。
 * 为什么这样做：把节点化主链路的低频状态与消息正文解耦，满足步骤条与调试抽屉的展示要求。
 * 输入输出：所有更新仅接收后端事件；组件层通过选择器读取投影状态。
 * 边界条件：前端不得自行推导未收到的节点状态，也不得修改后端已下发的真实结果。
 * 异常行为：无。
 */
export const useChatWorkflowStore = create<ChatWorkflowStoreState>((set, get) => ({
  activePlan: null,
  nodesByInteractionId: {},
  debugTimelineByTraceId: {},
  latestConditionResults: {},
  isStepBarVisible: true,
  expandedNodeTypes: {},
  expandedConditionReasons: {},
  metadataPanelExpandedByMessageId: {},
  isWorkflowDebugDrawerOpen: false,
  isCitationPanelVisible: false,

  onPlanStarted: (event) =>
    set((state) => {
      const activePlan: ChatPlanProjection = {
        schemaVersion: CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1,
        planPresetId: CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT,
        chatMode: CHAT_MODE.DAILY_CHAT,
        traceId: event.traceId,
        interactionId: event.interactionId,
        sessionId: event.sessionId,
        assistantMessageId: event.payload.assistantMessageId,
        status: 'running',
        startedAtMs: event.timestampMs,
        activeNodeType: event.nodeType,
        isPostprocessing: false,
        degradedNodeCount: 0,
        failedNodeCount: 0,
      };
      const previousTimeline = state.debugTimelineByTraceId[event.traceId];
      const debugTimelineByTraceId = {
        ...state.debugTimelineByTraceId,
        [event.traceId]: {
          traceId: event.traceId,
          interactionId: event.interactionId,
          events: trimDebugEvents([
            ...(previousTimeline?.events || []),
            buildDebugEvent(
              '计划开始',
              `已启动 ${CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT} 闲聊计划`,
              `assistant_message_id=${event.payload.assistantMessageId}`,
              event
            ),
          ]),
        },
      };
      return {
        activePlan,
        nodesByInteractionId: {
          ...state.nodesByInteractionId,
          [event.interactionId]: [],
        },
        debugTimelineByTraceId,
      };
    }),

  onNodeStatus: (event) =>
    set((state) => {
      const nodes = cloneNodeList(state.nodesByInteractionId[event.interactionId]);
      const nextNode: ChatNodeProjection = {
        nodeType: event.payload.nodeType,
        status: event.payload.status,
        startedAtMs: event.payload.startedAtMs,
        endedAtMs: event.payload.endedAtMs,
        latencyMs: event.payload.latencyMs,
        degradedReason: event.payload.degradedReason,
        errorCode: event.payload.errorCode,
        updatedAtMs: event.timestampMs,
      };
      const mergedNodes = upsertNodeProjection(nodes, nextNode);
      const traceTimeline = state.debugTimelineByTraceId[event.traceId];
      const statusLabel = event.payload.status === CHAT_NODE_STATUS.RUNNING
        ? '节点开始'
        : event.payload.status === CHAT_NODE_STATUS.DEGRADED
          ? '节点降级'
          : event.payload.status === CHAT_NODE_STATUS.FAILED
            ? '节点失败'
            : '节点完成';
      const debugEvent = buildDebugEvent(
        statusLabel,
        `${CHAT_WORKFLOW_NODE_LABEL[event.payload.nodeType]}：${event.payload.status}`,
        [
          event.payload.latencyMs !== undefined ? `latency_ms=${event.payload.latencyMs}` : '',
          event.payload.degradedReason ? `degraded_reason=${event.payload.degradedReason}` : '',
          event.payload.errorCode ? `error_code=${event.payload.errorCode}` : '',
        ]
          .filter(Boolean)
          .join(' | '),
        event
      );
      const updatedPlan =
        state.activePlan && state.activePlan.interactionId === event.interactionId
          ? {
              ...state.activePlan,
              activeNodeType: resolveActiveNodeType(mergedNodes),
              degradedNodeCount: mergedNodes.filter((item) => item.status === CHAT_NODE_STATUS.DEGRADED).length,
              failedNodeCount: mergedNodes.filter((item) => item.status === CHAT_NODE_STATUS.FAILED).length,
              status: derivePlanStatus(mergedNodes, state.activePlan.isPostprocessing),
            }
          : state.activePlan;
      return {
        activePlan: updatedPlan,
        nodesByInteractionId: {
          ...state.nodesByInteractionId,
          [event.interactionId]: mergedNodes,
        },
        debugTimelineByTraceId: {
          ...state.debugTimelineByTraceId,
          [event.traceId]: {
            traceId: event.traceId,
            interactionId: event.interactionId,
            events: trimDebugEvents([...(traceTimeline?.events || []), debugEvent]),
          },
        },
      };
    }),

  onConditionEvaluated: (event) =>
    set((state) => {
      const nodes = cloneNodeList(state.nodesByInteractionId[event.interactionId]);
      const nextStatus = event.payload.conditionEntered
        ? CHAT_NODE_STATUS.PENDING
        : CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION;
      const mergedNodes = upsertNodeProjection(nodes, {
        nodeType: event.payload.targetNodeType,
        status: nextStatus,
        conditionEntered: event.payload.conditionEntered,
        conditionReason: event.payload.reason,
        updatedAtMs: event.timestampMs,
      });
      const resultKey = buildConditionResultKey(event.interactionId, event.payload.targetNodeType);
      const traceTimeline = state.debugTimelineByTraceId[event.traceId];
      return {
        nodesByInteractionId: {
          ...state.nodesByInteractionId,
          [event.interactionId]: mergedNodes,
        },
        latestConditionResults: {
          ...state.latestConditionResults,
          [resultKey]: event.payload,
        },
        debugTimelineByTraceId: {
          ...state.debugTimelineByTraceId,
          [event.traceId]: {
            traceId: event.traceId,
            interactionId: event.interactionId,
            events: trimDebugEvents([
              ...(traceTimeline?.events || []),
              buildDebugEvent(
                '条件判断',
                `${CHAT_WORKFLOW_NODE_LABEL[event.payload.targetNodeType]}：${
                  event.payload.conditionEntered ? '已进入' : '未进入'
                }`,
                `route=${event.payload.routeName} | reason=${event.payload.reason}`,
                event
              ),
            ]),
          },
        },
      };
    }),

  onPostprocessStatus: (event, status) =>
    set((state) => {
      const traceTimeline = state.debugTimelineByTraceId[event.traceId];
      const activePlan =
        state.activePlan && state.activePlan.interactionId === event.interactionId
          ? {
              ...state.activePlan,
              isPostprocessing: status === 'started',
              status:
                status === 'started'
                  ? 'postprocessing'
                  : derivePlanStatus(
                      state.nodesByInteractionId[event.interactionId] || [],
                      false
                    ),
            }
          : state.activePlan;
      return {
        activePlan,
        debugTimelineByTraceId: {
          ...state.debugTimelineByTraceId,
          [event.traceId]: {
            traceId: event.traceId,
            interactionId: event.interactionId,
            events: trimDebugEvents([
              ...(traceTimeline?.events || []),
              buildDebugEvent(
                status === 'started' ? '后处理开始' : '后处理完成',
                status === 'started' ? '主回复已完成，开始执行后台整理' : '后台整理阶段已结束',
                `assistant_message_id=${event.payload.assistantMessageId}`,
                event
              ),
            ]),
          },
        },
      };
    }),

  onPlanCompleted: (event) =>
    set((state) => {
      const traceTimeline = state.debugTimelineByTraceId[event.traceId];
      const nodes = state.nodesByInteractionId[event.interactionId] || [];
      const nextStatus = nodes.some((item) => item.status === CHAT_NODE_STATUS.FAILED)
        ? 'failed'
        : state.activePlan?.isPostprocessing
          ? 'postprocessing'
          : 'completed';
      return {
        activePlan:
          state.activePlan && state.activePlan.interactionId === event.interactionId
            ? {
                ...state.activePlan,
                endedAtMs: event.timestampMs,
                status: nextStatus,
              }
            : state.activePlan,
        debugTimelineByTraceId: {
          ...state.debugTimelineByTraceId,
          [event.traceId]: {
            traceId: event.traceId,
            interactionId: event.interactionId,
            events: trimDebugEvents([
              ...(traceTimeline?.events || []),
              buildDebugEvent(
                '计划完成',
                '聊天主链路已完成本轮前台执行',
                `node_observation_count=${event.payload.nodeObservationCount}`,
                event
              ),
            ]),
          },
        },
      };
    }),

  clearInteraction: (interactionId) =>
    set((state) => {
      const nextNodesByInteractionId = { ...state.nodesByInteractionId };
      delete nextNodesByInteractionId[interactionId];
      const nextConditionResults = { ...state.latestConditionResults };
      Object.keys(nextConditionResults).forEach((key) => {
        if (key.startsWith(`${interactionId}:`)) {
          delete nextConditionResults[key];
        }
      });
      const activePlan = state.activePlan?.interactionId === interactionId ? null : state.activePlan;
      return {
        activePlan,
        nodesByInteractionId: nextNodesByInteractionId,
        latestConditionResults: nextConditionResults,
      };
    }),

  clearAll: () => ({
    activePlan: null,
    nodesByInteractionId: {},
    debugTimelineByTraceId: {},
    latestConditionResults: {},
    isStepBarVisible: true,
    expandedNodeTypes: {},
    expandedConditionReasons: {},
    metadataPanelExpandedByMessageId: {},
    isWorkflowDebugDrawerOpen: false,
    isCitationPanelVisible: false,
  }),

  setStepBarVisible: (visible) => set({ isStepBarVisible: visible }),

  toggleNodeExpanded: (interactionId, nodeType) =>
    set((state) => {
      const key = buildNodeUiKey(interactionId, nodeType);
      return {
        expandedNodeTypes: {
          ...state.expandedNodeTypes,
          [key]: !state.expandedNodeTypes[key],
        },
      };
    }),

  toggleConditionReasonExpanded: (interactionId, nodeType) =>
    set((state) => {
      const key = buildNodeUiKey(interactionId, nodeType);
      return {
        expandedConditionReasons: {
          ...state.expandedConditionReasons,
          [key]: !state.expandedConditionReasons[key],
        },
      };
    }),

  toggleMetadataPanelExpanded: (messageId) =>
    set((state) => ({
      metadataPanelExpandedByMessageId: {
        ...state.metadataPanelExpandedByMessageId,
        [messageId]: !state.metadataPanelExpandedByMessageId[messageId],
      },
    })),

  setWorkflowDebugDrawerOpen: (open) => set({ isWorkflowDebugDrawerOpen: open }),

  setCitationPanelVisible: (visible) => set({ isCitationPanelVisible: visible }),

  getMessageMetadata: (interactionId, assistantMessageId) => {
    if (!interactionId || !assistantMessageId) {
      return null;
    }
    const state = get();
    const nodes = state.nodesByInteractionId[interactionId] || [];
    if (nodes.length === 0) {
      return null;
    }
    const conditionBooleans = resolveConditionBooleans(state.latestConditionResults, interactionId);
    const postprocessErrors = nodes.filter(
      (item) => item.status === CHAT_NODE_STATUS.FAILED && CONDITION_NODE_TYPES.has(item.nodeType) === false
    );
    return {
      traceId: state.activePlan?.interactionId === interactionId ? state.activePlan.traceId : '',
      interactionId,
      assistantMessageId,
      planPresetId: CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT,
      activeNodeType: resolveActiveNodeType(nodes),
      enteredLongTermMemoryRag: conditionBooleans.enteredLongTermMemoryRag,
      enteredUserProfileInjection: conditionBooleans.enteredUserProfileInjection,
      enteredKnowledgeRag: conditionBooleans.enteredKnowledgeRag,
      hasDegradedNode: nodes.some((item) => item.status === CHAT_NODE_STATUS.DEGRADED),
      citations: [],
      nodeTimelineSummary: nodes,
      postprocessSummary:
        postprocessErrors.length > 0
          ? '本轮回复已完成，但后台整理存在未完成项目。'
          : state.activePlan?.interactionId === interactionId && state.activePlan.isPostprocessing
            ? '后台正在整理记忆与画像。'
            : undefined,
    };
  },
}));
