/**
 * Phase 9 DAG 工作流前端投影类型定义。
 * 做什么：定义前端 DAG 面板所需的全部数据投影结构，涵盖 Plan → State → Step → Node 四级嵌套。
 * 为什么这样做：前端 DAG 可视化面板的数据源完全由后端 SSE 事件驱动，
 *               投影结构是事件处理结果与 UI 渲染之间的桥梁。
 * 输入输出：由 dagWorkflowStore 维护，DagWorkflowPanel 及子组件消费。
 * 边界条件：所有字段都可能为空或 undefined，渲染时必须做空值保护。
 * 异常行为：无。
 */

import type { DagNodeStatus, DagNodeType } from '../../shared/enum';

// ============================================================
// Plan 层级
// ============================================================

/**
 * DAG Plan 状态常量。
 * 做什么：定义 Plan 整体生命周期的可能状态。
 * 为什么这样做：全局面板的状态着色和状态文案依赖此枚举。
 */
export type DagPlanStatus =
  | 'planning'         // 全局 Plan 生成中
  | 'executing'        // Plan 执行中
  | 'replanning'       // Plan 重构中
  | 'completed'        // 全部完成
  | 'terminated'       // 异常终止
  | 'budget_exhausted'; // 预算耗尽

/**
 * DAG Plan 状态中文标签映射。
 */
export const DAG_PLAN_STATUS_LABEL: Record<DagPlanStatus, string> = {
  planning: '规划中',
  executing: '执行中',
  replanning: '重新规划',
  completed: '已完成',
  terminated: '已终止',
  budget_exhausted: '预算耗尽',
};

/**
 * 全局总目标。
 * 做什么：描述 Plan 的全局目标、成功标准、输出格式和约束条件。
 * 为什么这样做：全局面板需要展示完整的任务目标信息。
 */
export interface DagGlobalObjective {
  /** 总体目标描述 */
  overallGoal: string;
  /** 成功标准 */
  successCriteria: string;
  /** 输出格式要求 */
  outputFormat: string;
  /** 约束条件列表 */
  constraints: string[];
}

/**
 * DAG Plan 投影视图 — 全局 Plan 层级。
 * 做什么：保存当前活跃的 Plan-State-Node 计划的完整投影。
 * 为什么这样做：前端 DAG 面板的顶层数据源，承载全局目标、State 列表和整体进度。
 */
export interface DagPlanProjection {
  /** 计划 ID（雪花算法） */
  planId: string;
  /** 会话 ID */
  sessionId: string;
  /** 追踪 ID */
  traceId: string;
  /** 交互 ID */
  interactionId: string;
  /** assistant 消息 ID */
  assistantMessageId: string;
  /** Plan 状态 */
  status: DagPlanStatus;
  /** 聊天模式（固定为 plan_state_node） */
  chatMode: 'plan_state_node';

  // 全局目标
  globalObjective: DagGlobalObjective;

  // State 列表（有序）
  states: DagStateProjection[];

  // 执行统计
  totalStates: number;
  completedStates: number;
  failedStates: number;

  // 时间
  startedAtMs: number;
  endedAtMs?: number;

  // 预算
  budgetConsumed: { tool_calls: number };
  budgetLimit: { max_total_tool_calls: number };

  // 规划推理说明
  planningReason: string;
}

// ============================================================
// State 层级
// ============================================================

/**
 * 完成条件条目。
 * 做什么：描述 State 的单个完成条件。
 * 为什么这样做：State 头部需要展示完成条件列表。
 */
export interface DagCompletionCriterion {
  /** 条件字段名 */
  field: string;
  /** 操作符 */
  operator: string;
  /** 期望值 */
  value: unknown;
}

/**
 * Skill 简介投影。
 * 做什么：保存 State 初筛阶段选中的 Skill 摘要信息。
 * 为什么这样做：State 容器内需要展示选中的 Skill 标签。
 */
export interface DagSkillBrief {
  /** Skill 名称 */
  skillName: string;
  /** Skill 描述 */
  description: string;
  /** 关联工具名称列表 */
  toolNames: string[];
  /** 能力标签列表 */
  capabilityTags: string[];
}

/**
 * State 评估结果投影。
 * 做什么：保存后端对 State 完成度的评估结果。
 * 为什么这样做：State 容器需要展示评估结果（通过/未通过 + 原因和差距分析）。
 */
export interface DagStateEvaluationResult {
  /** State 是否满足完成条件 */
  stateSatisfied: boolean;
  /** 评估原因 */
  evaluationReason: string;
  /** 差距分析 */
  gapAnalysis: string;
  /** 建议 */
  suggestion: string;
  /** 完成条件检查清单 */
  criteriaChecklist: { field: string; satisfied: boolean; detail: string }[];
  /** Agent CoT 系统校验推演过程 */
  check?: string;
}

/**
 * DAG State 投影视图 — State 层级。
 * 做什么：保存单个 State 的目标、状态、Step 列表和执行统计。
 * 为什么这样做：State 是 Plan-State-Node 的核心中间层，
 *               前端需要以可视化容器呈现每个 State 的边界。
 */
export interface DagStateProjection {
  /** State ID（雪花算法） */
  stateId: string;
  /** State 顺序索引 */
  orderIndex: number;
  /** State 意图 */
  intent: string;
  /** State 目标 */
  goal: string;
  /** 完成条件列表 */
  completionCriteria: DagCompletionCriterion[];
  /** 依赖的前置 State ID 列表 */
  dependsOn: string[];
  /** State 状态 */
  status: DagNodeStatus;

  // Skill 初筛结果
  selectedSkills: DagSkillBrief[];

  // Step 列表
  steps: DagStepProjection[];

  // 执行统计
  stepsCompleted: number;
  stepsTotal: number;
  nodesSucceeded: number;
  nodesFailed: number;

  // 评估结果
  evaluationResult?: DagStateEvaluationResult;

  // 时间
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;

  // 错误信息
  errorMessages: string[];
}

// ============================================================
// Step 层级
// ============================================================

/**
 * DAG Step 投影视图 — Step 层级。
 * 做什么：保存单个 Step 内的原子节点列表及执行模式。
 * 为什么这样做：Step 内部的节点可能并行执行（fan-out），
 *               前端需要区分并行/串行渲染。
 */
export interface DagStepProjection {
  /** Step ID（雪花算法） */
  stepId: string;
  /** Step 顺序索引 */
  stepIndex: number;
  /** Step 描述 */
  description: string;
  /** Step 状态 */
  status: DagNodeStatus;
  /** 执行模式：parallel（并行）或 serial（串行） */
  executionMode: 'parallel' | 'serial';

  // 原子节点列表
  nodes: DagNodeProjection[];

  // 时间
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;
}

// ============================================================
// Node 层级
// ============================================================

/**
 * 中间产物 / 日志条目。
 * 做什么：记录节点执行过程中的中间信息（如工具调用参数、LLM 推理片段）。
 * 为什么这样做：调试面板需要可展开的中间日志来排查问题。
 */
export interface DagIntermediateLog {
  /** 日志 ID */
  logId: string;
  /** 时间戳（毫秒） */
  timestampMs: number;
  /** 日志级别 */
  level: 'info' | 'warn' | 'error' | 'debug';
  /** 日志消息 */
  message: string;
  /** 附加数据 */
  data?: unknown;
}

/**
 * DAG 原子节点投影视图 — Node 层级。
 * 做什么：保存单个原子节点的完整状态，包括输入输出参数和运行时信息。
 * 为什么这样做：这是 DAG 可视化最细粒度的数据单元。
 */
export interface DagNodeProjection {
  /** 节点 ID（雪花算法） */
  nodeId: string;
  /** 节点类型 */
  nodeType: DagNodeType;
  /** 节点状态 */
  status: DagNodeStatus;
  /** 节点描述 */
  description: string;

  // 节点元数据
  /** 关联的 Skill 名称 */
  skillName?: string;
  /** 关联的工具名称 */
  toolName?: string;
  /** 关联的资源名称 */
  resourceName?: string;
  /** 是否需要 Gating 审批 */
  gatingRequired: boolean;

  // 输入参数
  inputs: Record<string, unknown>;

  // 输出参数
  outputs: Record<string, unknown>;

  /** Agent CoT 系统校验推演过程。做什么：展示 LLM 在生成最终输出前的自检过程。 */
  check?: string;

  // 中间产物 / 日志
  intermediateLogs: DagIntermediateLog[];

  // 时间
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;

  // 错误与重试
  errorMessage?: string;
  retryCount: number;
  maxRetries: number;
}
