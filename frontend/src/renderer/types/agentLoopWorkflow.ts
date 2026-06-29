/**
 * Agent Loop 工作流前端投影类型定义。
 *
 * 做什么：定义 Agent Loop 万能循环模式前端面板所需的全部数据投影结构，
 *         涵盖 Goal → Plan → Step Loop（Think → Execute → Observe → Evaluate → Repair/Replan）→ FinalVerify。
 * 为什么这样做：Agent Loop 的数据结构（Goal 锁定 + 可变 Plan + 步进 Step Loop）与
 *               Plan-State-Node 的四层嵌套完全不同，需要独立类型以避免污染 dagWorkflowStore。
 * 输入输出：由 agentLoopStore 维护，AgentLoopPanel 及子组件消费。
 * 边界条件：所有字段都可能为空或 undefined，渲染时必须做空值保护。
 * 异常行为：无。
 */

// ============================================================
// 目标层级（GoalState — 只写一次）
// ============================================================

/**
 * 全局目标投影。
 * 做什么：存储锁定后的全局目标、验收标准、非目标声明。
 * 为什么这样做：Agent Loop 面板顶部需要展示目标信息，且支持收起/展开。
 */
export interface AgentLoopGoal {
  /** 任务 ID */
  taskId: string;
  /** 全局总目标描述 */
  globalGoal: string;
  /** 目标详细描述 */
  goalDefinition: string;
  /** 验收标准列表 */
  acceptanceCriteria: string[];
  /** 非目标声明 */
  nonGoals: string[];
  /** 约束条件 */
  constraints: string[];
  /** 是否已锁定 */
  locked: boolean;
  /** 锁定时间戳 */
  lockedAtMs: number;
}

// ============================================================
// 计划层级（PlanState — 可变，版本化）
// ============================================================

/**
 * Agent Loop 步骤状态。
 */
export type AgentStepStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

/**
 * Agent Loop 计划投影。
 * 做什么：存储当前全局步骤序列，支持版本化和 replan 历史。
 */
export interface AgentLoopPlan {
  /** 计划版本号 */
  planVersion: number;
  /** 步骤列表 */
  steps: AgentStepProjection[];
  /** 当前执行到第几步 */
  currentStepIndex: number;
  /** replan 历史 */
  replanHistory: AgentReplanRecord[];
}

/**
 * Replan 历史记录。
 */
export interface AgentReplanRecord {
  fromVersion: number;
  toVersion: number;
  reason: string;
  failedStepId: string;
  changedStepIds: string[];
  timestampMs: number;
}

/**
 * 单步投影。
 * 做什么：描述一个可执行步骤的元信息和运行时状态。
 */
export interface AgentStepProjection {
  stepId: string;
  title: string;
  intent: string;
  dependencies: string[];
  expectedOutput: string;
  status: AgentStepStatus;
  riskNotes: string;
  rollbackHint: string;

  // === 执行详情（Agent Loop 特有）===
  /** StepThinkNode 输出的思考结果 */
  lastThought: string;
  /** 规划的工具调用列表 */
  toolCalls: AgentToolCall[];
  /** 工具执行结果 */
  toolResults: AgentToolResult[];
  /** ObserveNode 输出的结构化观察 */
  lastObservation: string;
  /** StepEvaluateNode 的评估结果 */
  evaluationResult?: AgentStepEvaluation;
  /** StepRepairNode 的修复次数 */
  repairCount: number;
  /** 重试次数 */
  retryCount: number;

  // === 循环迭代记录（万能循环核心）===
  /**
   * 已完成的循环迭代列表。
   * 做什么：记录每个 Step 中 Think → Execute → Observe → Evaluate 的完整循环迭代。
   * 为什么这样做：一个步骤可能经历多次循环（fail → repair → re-think → re-execute），
   *               每次迭代的历史必须完整保留，而不是被覆盖。
   * 边界条件：当步骤正在进行中时，当前活跃迭代不在此列表中（从 live 字段读取）。
   */
  loopIterations: AgentLoopIteration[];
  /** 当前正在执行的循环迭代索引（从 1 开始，用于展示标签） */
  currentIterationIndex: number;

  // === 时间 ===
  startedAtMs?: number;
  endedAtMs?: number;
  latencyMs?: number;
}

/**
 * 单次循环迭代快照。
 * 做什么：记录 Step 内一次 Think → Execute → Observe → Evaluate 的完整快照。
 * 为什么这样做：一个 Step 可能经历多次循环（fail → repair → re-think → re-execute），
 *               每次迭代的历史必须完整保留，供前端展示完整的循环过程。
 * 边界条件：toolCalls 和 toolResults 可能为空数组（纯思考步骤走 fast_pass 路径）。
 * 异常行为：无。
 */
export interface AgentLoopIteration {
  /** 迭代索引（从 1 开始） */
  iterationIndex: number;
  /** 思考结果 */
  thought: string;
  /** 规划的工具调用列表 */
  toolCalls: AgentToolCall[];
  /** 工具执行结果 */
  toolResults: AgentToolResult[];
  /** 观察结果 */
  observation: string;
  /** 评估结果 */
  evaluationResult?: AgentStepEvaluation;
  /** 迭代开始时间戳 */
  startedAtMs?: number;
  /** 迭代结束时间戳 */
  endedAtMs?: number;
  /** 迭代总耗时（毫秒） */
  latencyMs?: number;
}

/**
 * 工具调用投影。
 */
export interface AgentToolCall {
  toolName: string;
  skillName: string;
  parameters: Record<string, unknown>;
  /** 调用原因 / 用途说明 */
  purpose: string;
  /**
   * Gating 审批状态。
   * 做什么：记录该工具调用在权限审批流程中的当前状态。
   * 为什么这样做：用户在审批弹窗中做出决策后，需要在 Agent Loop 的工具调用卡片中
   *               实时展示审批结果（橙色等待 / 绿色通过 / 红色拒绝），
   *               而不是仅在弹窗关闭后丢失审批上下文。
   * 边界条件：
   *   - undefined 表示该工具不需要审批或审批流程尚未开始。
   *   - 'awaiting_approval' 表示正在等待用户决策（橙色高亮）。
   *   - 'approved' 表示用户已同意，工具正在执行或已执行完成。
   *   - 'rejected' 表示用户已拒绝，工具不会被执行。
   */
  approvalStatus?: 'awaiting_approval' | 'approved' | 'rejected';
}

/**
 * 工具执行结果投影。
 */
export interface AgentToolResult {
  nodeId: string;
  toolName: string;
  success: boolean;
  toolOutput: string;
  errorMessage: string;
  latencyMs: number;
  retryCount: number;
}

/**
 * Step 评估结果投影。
 */
export interface AgentStepEvaluation {
  /** 评估结论 */
  verdict: 'pass' | 'fail' | 'partial' | 'needs_replan';
  /** 评估理由 */
  evaluationReason: string;
  /** 差距分析 */
  gapAnalysis: string;
  /** 改进建议 */
  suggestion: string;
  /** 完成条件检查清单 */
  criteriaChecklist: { criterion: string; met: boolean; evidence: string }[];
}

// ============================================================
// 预算层级（BudgetState）
// ============================================================

/**
 * 预算投影。
 */
export interface AgentBudgetState {
  tokenUsed: number;
  toolCallsUsed: number;
  stepRetriesUsed: number;
  replanCount: number;
  timeUsedMs: number;
  maxToolCalls: number;
  maxStepRetries: number;
  maxReplanCount: number;
  maxTimeMs: number;
}

// ============================================================
// 最终验收
// ============================================================

/**
 * 最终验收投影。
 *
 * 做什么：定义最终验收结果的二值化状态。
 * 为什么这样做：无论验收是否通过，路由都进入主 Chat LLM 汇总节点，
 *               前端渲染时根据 pass/fail 分别显示"通过"（绿色）或"失败"（红色）。
 *               pass=全部标准满足；fail=存在未满足标准或异常。
 */
export interface AgentFinalVerification {
  status: 'pass' | 'fail';
  report: string;
  allCriteriaMet: boolean;
  criteriaVerification: { criterion: string; met: boolean; evidence: string }[];
}

// ============================================================
// 顶层 Plan 投影
// ============================================================

/**
 * Agent Loop 整体状态。
 */
export type AgentLoopStatus =
  | 'goal_locking'
  | 'planning'
  | 'executing'
  | 'replanning'
  | 'verifying'
  | 'completed'
  | 'completed_with_gaps'
  | 'terminated'
  | 'budget_exhausted';

/**
 * Agent Loop 状态中文标签映射。
 */
export const AGENT_LOOP_STATUS_LABEL: Record<AgentLoopStatus, string> = {
  goal_locking: '目标锁定中',
  planning: '计划生成中',
  executing: '步进执行中',
  replanning: '重新规划中',
  verifying: '最终验收中',
  completed: '已完成',
  completed_with_gaps: '部分完成',
  terminated: '已终止',
  budget_exhausted: '预算耗尽',
};

/**
 * Agent Loop 投影视图 — 顶层。
 * 做什么：保存当前活跃的 Agent Loop 计划的完整投影。
 */
export interface AgentLoopProjection {
  /** 计划 ID */
  planId: string;
  /** 会话 ID */
  sessionId: string;
  /** 追踪 ID */
  traceId: string;
  /** 整体状态 */
  status: AgentLoopStatus;
  /** 聊天模式 */
  chatMode: 'agent_loop';

  // 全局目标
  goal: AgentLoopGoal;

  // 计划
  plan: AgentLoopPlan;

  // 预算
  budget: AgentBudgetState;

  // 最终验收
  finalVerification?: AgentFinalVerification;

  // 时间
  startedAtMs: number;
  endedAtMs?: number;
  elapsedMs?: number;
}
