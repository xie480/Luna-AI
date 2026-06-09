import type {
  ChatCitationProjection,
  ChatConditionEvaluatedPayload,
  ChatMode,
  ChatNodeStatus,
  ChatPlanPreset,
  ChatWorkflowEventType,
  ChatWorkflowNodeType,
} from '../../shared/types';
import { CHAT_WORKFLOW_SCHEMA_VERSION } from '../../shared/enum';

/**
 * Chat Plan 投影视图状态。
 * 做什么：描述前端当前持有的单轮闲聊计划所处阶段。
 * 为什么这样做：Phase 8.5 需要区分主回复执行中、后处理中、已完成和失败等展示语义。
 * 输入输出：无。
 * 边界条件：当前仅服务于单一日常闲聊 plan，不代表完整 DAG 生命周期。
 * 异常行为：无。
 */
export type ChatPlanStatus = 'running' | 'postprocessing' | 'completed' | 'failed';

/**
 * Chat Plan 投影视图。
 * 做什么：保存当前活跃闲聊计划的最小摘要信息。
 * 为什么这样做：前端只需要知道“本轮回复属于哪个计划、当前跑到哪个节点”，不需要完整 DAG。
 * 输入输出：输入来自后端计划生命周期事件，输出给步骤条、元数据面板与调试面板消费。
 * 边界条件：`activeNodeType` 在计划刚启动或已完成时可能为空。
 * 异常行为：无。
 */
export interface ChatPlanProjection {
  schemaVersion: typeof CHAT_WORKFLOW_SCHEMA_VERSION.CHAT_WORKFLOW_V1;
  planPresetId: ChatPlanPreset;
  chatMode: ChatMode;
  traceId: string;
  interactionId: string;
  sessionId: string;
  assistantMessageId: string;
  status: ChatPlanStatus;
  startedAtMs: number;
  endedAtMs?: number;
  activeNodeType?: ChatWorkflowNodeType;
  isPostprocessing: boolean;
  degradedNodeCount: number;
  failedNodeCount: number;
}

/**
 * Chat 节点投影视图。
 * 做什么：保存单个节点在当前 interaction 下的状态、耗时、条件结果与降级信息。
 * 为什么这样做：节点状态必须完全以后端事件为准，前端只负责做轻量映射与展示。
 * 输入输出：输入来自节点状态事件与条件评估事件，输出给步骤条、时间线与条件展示组件。
 * 边界条件：条件节点只在收到条件评估事件后才会填充 `conditionEntered` 与 `conditionReason`。
 * 异常行为：无。
 */
export interface ChatNodeProjection {
  nodeType: ChatWorkflowNodeType;
  status: ChatNodeStatus;
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;
  conditionEntered?: boolean;
  conditionReason?: string;
  degradedReason?: string;
  errorCode?: string;
  updatedAtMs: number;
}

/**
 * Chat Workflow 调试事件。
 * 做什么：保存节点化计划的时间线事件摘要。
 * 为什么这样做：调试抽屉需要按 trace_id 回看计划启动、节点流转、条件判断和后处理过程。
 * 输入输出：输入来自 workflow store 写入，输出给时间线组件按列表展示。
 * 边界条件：`detail` 与 `payloadSummary` 只保留可展示摘要，避免普通 UI 暴露过多敏感内容。
 * 异常行为：无。
 */
export interface ChatWorkflowDebugEvent {
  eventId: string;
  eventType: ChatWorkflowEventType;
  nodeType?: ChatWorkflowNodeType;
  timestampMs: number;
  title: string;
  detail: string;
  payloadSummary: string;
}

/**
 * Chat Workflow 调试时间线。
 * 做什么：承载某个 trace_id 下最近的一组节点化工作流事件。
 * 为什么这样做：高频调试信息不应混入主聊天状态，避免无谓重渲染。
 * 输入输出：输入为 trace_id 与事件列表，输出给调试面板按需渲染。
 * 边界条件：事件列表会在 store 中按固定上限裁剪。
 * 异常行为：无。
 */
export interface ChatWorkflowDebugTimeline {
  traceId: string;
  interactionId: string;
  events: ChatWorkflowDebugEvent[];
}

/**
 * Assistant 消息上的 workflow 元数据投影。
 * 做什么：把节点化计划摘要附着到某条 assistant 消息，供元数据面板使用。
 * 为什么这样做：这些结构化信息不应污染消息正文，但需要和最终回复建立稳定关联。
 * 输入输出：输入来自 workflow store 与流式事件，输出给元数据面板和调试入口。
 * 边界条件：普通消息没有 workflow 数据时该对象可以缺省。
 * 异常行为：无。
 */
export interface ChatWorkflowMessageMetadata {
  traceId: string;
  interactionId: string;
  assistantMessageId: string;
  planPresetId: ChatPlanPreset;
  activeNodeType?: ChatWorkflowNodeType;
  enteredLongTermMemoryRag?: boolean;
  enteredUserProfileInjection?: boolean;
  enteredKnowledgeRag?: boolean;
  hasDegradedNode: boolean;
  citations: ChatCitationProjection[];
  nodeTimelineSummary: ChatNodeProjection[];
  postprocessSummary?: string;
}

/**
 * 条件节点结果索引。
 * 做什么：用 interaction 与目标节点类型索引条件判断结果。
 * 为什么这样做：同一 interaction 中可能存在多个条件节点，组件读取时需要稳定键值。
 * 输入输出：输入来自条件评估事件，输出给条件节点展示和元数据面板。
 * 边界条件：当前仅覆盖长期记忆、用户画像、知识库三个条件节点。
 * 异常行为：无。
 */
export type ChatConditionResultMap = Record<string, ChatConditionEvaluatedPayload>;
