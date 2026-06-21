/**
 * Phase 9 DAG 工作流状态管理。
 * 做什么：维护 Plan-State-Node 四级投影数据，响应后端 SSE 事件驱动 UI 更新。
 * 为什么这样做：DAG 工作流的数据结构（四层嵌套树）与 Phase 8.5 的扁平节点列表完全不同，
 *               需要独立 Store 以避免污染日常聊天模式的组件和数据。
 * 输入输出：由 SSEManager 调用事件处理方法，DagWorkflowPanel 及子组件通过 selector 消费。
 * 边界条件：activePlan 为 null 时 DAG 面板不渲染。
 * 异常行为：无。
 */
import { create } from 'zustand';
import { DAG_NODE_STATUS } from '../../shared/enum';
import type {
  DagPlanCreatedPayload,
  DagStateStartedPayload,
  DagSkillScreeningPayload,
  DagStepPlanPayload,
  DagNodeStartedPayload,
  DagNodeCompletedPayload,
  DagNodeGatingPayload,
  DagStateEvaluatedPayload,
  DagPlanReplannedPayload,
  DagPlanCompletedPayload,
  DagPlanTerminatedPayload,
  DagBudgetExhaustedPayload,
} from '../../shared/types';
import type {
  DagPlanProjection,
  DagStateProjection,
  DagStepProjection,
  DagNodeProjection,
  DagPlanStatus,
} from '../types/dagWorkflow';

// ============================================================
// Store 状态接口
// ============================================================

/**
 * DAG 工作流 Store 状态接口。
 * 做什么：定义 Store 的完整状态结构，包括核心数据、UI 展示状态和事件处理方法。
 * 为什么这样做：Zustand Store 需要明确的类型定义以保证类型安全。
 */
interface DagWorkflowStoreState {
  // === 核心数据 ===
  /** 当前活跃的 Plan 投影 */
  activePlan: DagPlanProjection | null;

  /** 按 planId 索引的历史投影 */
  planHistory: Record<string, DagPlanProjection>;

  // === UI 展示状态 ===
  /** DAG 面板是否展开 */
  isPanelVisible: boolean;
  /** State 容器展开/折叠状态（按 stateId 索引） */
  expandedStates: Record<string, boolean>;
  /** Step 容器展开/折叠状态（按 stepId 索引） */
  expandedSteps: Record<string, boolean>;
  /** Node 详情展开/折叠状态（按 nodeId 索引） */
  expandedNodes: Record<string, boolean>;
  /** 节点搜索关键词 */
  searchQuery: string;
  /** 画布缩放比例 */
  canvasZoom: number;
  /** 画布平移偏移 */
  canvasOffset: { x: number; y: number };

  // === 事件处理方法 ===
  /** 处理 Plan 创建事件 */
  onPlanCreated: (payload: DagPlanCreatedPayload, traceId: string) => void;
  /** 处理 State 启动事件 */
  onStateStarted: (payload: DagStateStartedPayload) => void;
  /** 处理 Skill 初筛事件 */
  onSkillScreening: (payload: DagSkillScreeningPayload) => void;
  /** 处理 Step Plan 生成事件 */
  onStepPlanGenerated: (payload: DagStepPlanPayload) => void;
  /** 处理节点启动事件 */
  onNodeStarted: (payload: DagNodeStartedPayload) => void;
  /** 处理节点完成事件 */
  onNodeCompleted: (payload: DagNodeCompletedPayload) => void;
  /** 处理节点 Gating 审批事件 */
  onNodeGating: (payload: DagNodeGatingPayload) => void;
  /** 处理 State 评估事件 */
  onStateEvaluated: (payload: DagStateEvaluatedPayload) => void;
  /** 处理 Plan 重构事件 */
  onPlanReplanned: (payload: DagPlanReplannedPayload) => void;
  /** 处理 Plan 完成事件 */
  onPlanCompleted: (payload: DagPlanCompletedPayload) => void;
  /** 处理 Plan 终止事件 */
  onPlanTerminated: (payload: DagPlanTerminatedPayload) => void;
  /** 处理预算耗尽事件 */
  onBudgetExhausted: (payload: DagBudgetExhaustedPayload) => void;

  // === UI 操作方法 ===
  /** 设置面板可见性 */
  setPanelVisible: (visible: boolean) => void;
  /** 切换 State 容器展开/折叠 */
  toggleStateExpanded: (stateId: string) => void;
  /** 切换 Step 容器展开/折叠 */
  toggleStepExpanded: (stepId: string) => void;
  /** 切换 Node 详情展开/折叠 */
  toggleNodeExpanded: (nodeId: string) => void;
  /** 设置搜索关键词 */
  setSearchQuery: (query: string) => void;
  /** 设置画布缩放比例 */
  setCanvasZoom: (zoom: number) => void;
  /** 设置画布平移偏移 */
  setCanvasOffset: (offset: { x: number; y: number }) => void;
  /** 清除当前 Plan */
  clearPlan: () => void;
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 从 DagStepPlanPayload 的 nodes 数组创建 DagNodeProjection 列表。
 * 做什么：将后端推送的原始节点数据转换为前端投影结构。
 * 为什么这样做：后端 Payload 使用 snake_case，前端投影使用 camelCase，需要映射。
 */
function createNodeProjections(
  nodes: DagStepPlanPayload['steps'][0]['nodes']
): DagNodeProjection[] {
  return nodes.map((node) => ({
    nodeId: node.node_id,
    nodeType: node.node_type as DagNodeProjection['nodeType'],
    status: DAG_NODE_STATUS.PENDING,
    description: node.parameter_hint || node.transform_instruction || node.query_text || node.node_type,
    skillName: node.skill_name,
    toolName: node.tool_name,
    resourceName: node.resource_name,
    gatingRequired: node.gating_required,
    inputs: {},
    outputs: {},
    intermediateLogs: [],
    retryCount: 0,
    maxRetries: 3,
  }));
}

/**
 * 在 Plan 的 State 列表中查找指定 State。
 * 做什么：按 stateId 在嵌套结构中定位 State 投影。
 * 为什么这样做：事件处理方法需要频繁按 stateId 查找 State。
 */
function findState(plan: DagPlanProjection, stateId: string): DagStateProjection | undefined {
  return plan.states.find((s) => s.stateId === stateId);
}

/**
 * 在 State 的 Step 列表中查找指定 Step。
 * 做什么：按 stepId 在嵌套结构中定位 Step 投影。
 * 为什么这样做：事件处理方法需要频繁按 stepId 查找 Step。
 */
function findStep(state: DagStateProjection, stepId: string): DagStepProjection | undefined {
  return state.steps.find((s) => s.stepId === stepId);
}

/**
 * 在 Step 的 Node 列表中查找指定 Node。
 * 做什么：按 nodeId 在嵌套结构中定位 Node 投影。
 * 为什么这样做：事件处理方法需要频繁按 nodeId 查找 Node。
 */
function findNode(step: DagStepProjection, nodeId: string): DagNodeProjection | undefined {
  return step.nodes.find((n) => n.nodeId === nodeId);
}

/**
 * 在整个 Plan 中搜索包含指定 nodeId 的 Node。
 * 做什么：遍历 Plan → State → Step → Node 四级结构查找目标节点。
 * 为什么这样做：部分事件仅携带 nodeId 而不携带 stepId，需要全局搜索。
 */
function findNodeInPlan(
  plan: DagPlanProjection,
  nodeId: string
): { state: DagStateProjection; step: DagStepProjection; node: DagNodeProjection } | undefined {
  for (const state of plan.states) {
    for (const step of state.steps) {
      const node = findNode(step, nodeId);
      if (node) {
        return { state, step, node };
      }
    }
  }
  return undefined;
}

/**
 * 重新计算 Plan 的全局统计信息。
 * 做什么：遍历所有 State 更新 completedStates 和 failedStates 计数。
 * 为什么这样做：多个事件可能改变 State 状态，需要在变更后重新统计。
 */
function recalcPlanStats(plan: DagPlanProjection): void {
  plan.completedStates = plan.states.filter(
    (s) => s.status === DAG_NODE_STATUS.SUCCEEDED
  ).length;
  plan.failedStates = plan.states.filter(
    (s) => s.status === DAG_NODE_STATUS.FAILED
  ).length;
  plan.totalStates = plan.states.length;
}

/**
 * 重新计算 State 的执行统计信息。
 * 做什么：遍历 State 内所有 Step 和 Node 更新统计计数。
 * 为什么这样做：节点完成事件后需要更新 State 级别的统计。
 */
function recalcStateStats(state: DagStateProjection): void {
  state.stepsCompleted = state.steps.filter(
    (s) => s.status === DAG_NODE_STATUS.SUCCEEDED || s.status === DAG_NODE_STATUS.DEGRADED
  ).length;
  state.stepsTotal = state.steps.length;

  let succeeded = 0;
  let failed = 0;
  for (const step of state.steps) {
    for (const node of step.nodes) {
      if (node.status === DAG_NODE_STATUS.SUCCEEDED || node.status === DAG_NODE_STATUS.DEGRADED) {
        succeeded++;
      } else if (node.status === DAG_NODE_STATUS.FAILED) {
        failed++;
      }
    }
  }
  state.nodesSucceeded = succeeded;
  state.nodesFailed = failed;
}

/**
 * 推导 Step 的整体状态。
 * 做什么：根据 Step 内所有节点的状态推导 Step 的聚合状态。
 * 为什么这样做：Step 的状态由其内部节点状态决定，不能由前端自行设定。
 * 规则：
 *   - 所有节点 SUCCEEDED/DEGRADED → SUCCEEDED
 *   - 任一节点 FAILED → FAILED
 *   - 任一节点 RUNNING → RUNNING
 *   - 其余 → PENDING
 */
function deriveStepStatus(step: DagStepProjection): void {
  const statuses = step.nodes.map((n) => n.status);
  if (statuses.length === 0) return;

  if (statuses.some((s) => s === DAG_NODE_STATUS.FAILED)) {
    step.status = DAG_NODE_STATUS.FAILED;
  } else if (statuses.some((s) => s === DAG_NODE_STATUS.RUNNING)) {
    step.status = DAG_NODE_STATUS.RUNNING;
  } else if (statuses.every((s) => s === DAG_NODE_STATUS.SUCCEEDED || s === DAG_NODE_STATUS.DEGRADED || s === DAG_NODE_STATUS.SKIPPED)) {
    step.status = DAG_NODE_STATUS.SUCCEEDED;
  } else {
    step.status = DAG_NODE_STATUS.PENDING;
  }
}

// ============================================================
// Store 实现
// ============================================================

/**
 * 创建 DAG 工作流 Store。
 * 做什么：使用 Zustand 创建 DAG 工作流的状态管理实例。
 * 为什么这样做：独立于 chatWorkflowStore，避免日常聊天模式加载 DAG 的复杂数据结构。
 */
export const useDagWorkflowStore = create<DagWorkflowStoreState>((set, get) => ({
  // === 核心数据初始值 ===
  activePlan: null,
  planHistory: {},

  // === UI 展示状态初始值 ===
  isPanelVisible: false,
  expandedStates: {},
  expandedSteps: {},
  expandedNodes: {},
  searchQuery: '',
  canvasZoom: 1,
  canvasOffset: { x: 0, y: 0 },

  // ============================================================
  // 事件处理方法
  // ============================================================

  /**
   * 处理 Plan 创建事件。
   * 做什么：将后端推送的 Plan 结构转换为前端投影并设为活跃 Plan。
   * 为什么这样做：这是 DAG 面板的数据入口，后续所有事件都基于此投影进行增量更新。
   */
  onPlanCreated: (payload, traceId) => {
    const now = Date.now();

    // 将后端 Payload 映射为前端 State 投影
    const states: DagStateProjection[] = payload.states.map((s) => ({
      stateId: s.state_id,
      orderIndex: s.order_index,
      intent: s.intent,
      goal: s.goal,
      completionCriteria: s.completion_criteria.map((c) => ({
        field: c.field,
        operator: c.operator,
        value: c.value,
      })),
      dependsOn: s.depends_on,
      status: DAG_NODE_STATUS.PENDING,
      selectedSkills: [],
      steps: [],
      stepsCompleted: 0,
      stepsTotal: 0,
      nodesSucceeded: 0,
      nodesFailed: 0,
      errorMessages: [],
    }));

    const plan: DagPlanProjection = {
      planId: payload.plan_id,
      sessionId: payload.session_id,
      traceId,
      interactionId: payload.interaction_id,
      assistantMessageId: payload.assistant_message_id,
      status: 'planning',
      chatMode: 'plan_state_node',
      globalObjective: {
        overallGoal: payload.global_objective.overall_goal,
        successCriteria: payload.global_objective.success_criteria,
        outputFormat: payload.global_objective.output_format,
        constraints: payload.global_objective.constraints,
      },
      states,
      totalStates: states.length,
      completedStates: 0,
      failedStates: 0,
      startedAtMs: now,
      budgetConsumed: { tool_calls: 0 },
      budgetLimit: { max_total_tool_calls: 50 },
      planningReason: payload.planning_reason,
    };

    // 自动展开第一个 State
    const expandedStates: Record<string, boolean> = {};
    if (states.length > 0) {
      expandedStates[states[0].stateId] = true;
    }

    set({
      activePlan: plan,
      isPanelVisible: true,
      expandedStates,
      expandedSteps: {},
      expandedNodes: {},
      canvasZoom: 1,
      canvasOffset: { x: 0, y: 0 },
    });
  },

  /**
   * 处理 State 启动事件。
   * 做什么：将目标 State 状态切换为 RUNNING，记录启动时间。
   * 为什么这样做：前端需要高亮当前 State 容器并启动耗时计时器。
   */
  onStateStarted: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      plan.status = 'executing';
      const targetState = findState(plan, payload.state_id);
      if (targetState) {
        targetState.status = DAG_NODE_STATUS.RUNNING;
        targetState.startedAtMs = Date.now();
      }
      // 自动展开当前 State
      return {
        activePlan: plan,
        expandedStates: { ...state.expandedStates, [payload.state_id]: true },
      };
    });
  },

  /**
   * 处理 Skill 初筛事件。
   * 做什么：将选中的 Skill 列表写入目标 State 的 selectedSkills 字段。
   * 为什么这样做：State 容器内需要展示选中的 Skill 标签。
   */
  onSkillScreening: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const targetState = findState(plan, payload.state_id);
      if (targetState) {
        targetState.selectedSkills = payload.selected_skills.map((s) => ({
          skillName: s.skill_name,
          description: s.description,
          toolNames: s.tool_names,
          capabilityTags: s.capability_tags,
        }));
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理 Step Plan 生成事件。
   * 做什么：将后端推送的 Step 列表转换为前端投影并写入目标 State。
   * 为什么这样做：State 容器需要渲染 Step 列表及其中的节点卡片。
   */
  onStepPlanGenerated: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const targetState = findState(plan, payload.state_id);
      if (targetState) {
        targetState.steps = payload.steps.map((s) => ({
          stepId: s.step_id,
          stepIndex: s.step_index,
          description: s.description,
          status: DAG_NODE_STATUS.PENDING,
          executionMode: s.execution_mode,
          nodes: createNodeProjections(s.nodes),
        }));
        targetState.stepsTotal = targetState.steps.length;
        // 自动展开第一个 Step
        if (targetState.steps.length > 0) {
          const newExpandedSteps = { ...state.expandedSteps };
          newExpandedSteps[targetState.steps[0].stepId] = true;
          return { activePlan: plan, expandedSteps: newExpandedSteps };
        }
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理节点启动事件。
   * 做什么：将目标节点状态切换为 RUNNING，记录启动时间。
   * 为什么这样做：节点卡片需要进入执行态并显示耗时计时器。
   */
  onNodeStarted: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const result = findNodeInPlan(plan, payload.node_id);
      if (result) {
        result.node.status = DAG_NODE_STATUS.RUNNING;
        result.node.startedAtMs = Date.now();
        // 更新 Step 状态
        deriveStepStatus(result.step);
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理节点完成事件。
   * 做什么：更新节点状态、输出参数和耗时，重新计算 Step 和 State 统计。
   * 为什么这样做：这是 DAG 可视化的核心状态更新事件。
   */
  onNodeCompleted: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const result = findNodeInPlan(plan, payload.node_id);
      if (result) {
        const { node, step, state: dagState } = result;
        // 更新节点状态
        node.status = payload.success ? DAG_NODE_STATUS.SUCCEEDED : DAG_NODE_STATUS.FAILED;
        node.outputs = payload.outputs;
        node.latencyMs = payload.latency_ms;
        node.retryCount = payload.retry_count;
        node.endedAtMs = Date.now();
        if (!payload.success && payload.error_message) {
          node.errorMessage = payload.error_message;
        }
        // 推导 Step 状态
        deriveStepStatus(step);
        // 重新计算 State 统计
        recalcStateStats(dagState);
        // 重新计算 Plan 统计
        recalcPlanStats(plan);
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理节点 Gating 审批事件。
   * 做什么：将目标节点状态切换为 PENDING_USER_APPROVAL。
   * 为什么这样做：节点卡片需要显示「等待审批」状态，Gating 弹窗由外部组件处理。
   */
  onNodeGating: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const result = findNodeInPlan(plan, payload.node_id);
      if (result) {
        result.node.status = DAG_NODE_STATUS.PENDING_USER_APPROVAL;
        // 将 gating 信息写入 inputs 以便 UI 展示
        result.node.inputs = {
          ...result.node.inputs,
          _gating: {
            tool_name: payload.tool_name,
            parameters: payload.parameters,
            risk_level: payload.risk_level,
          },
        };
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理 State 评估事件。
   * 做什么：将评估结果写入目标 State 的 evaluationResult 字段。
   * 为什么这样做：State 容器需要展示评估结果（通过/未通过 + 原因）。
   */
  onStateEvaluated: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      const targetState = findState(plan, payload.state_id);
      if (targetState) {
        targetState.evaluationResult = {
          stateSatisfied: payload.state_satisfied,
          evaluationReason: payload.evaluation_reason,
          gapAnalysis: payload.gap_analysis,
          suggestion: payload.suggestion,
          criteriaChecklist: payload.criteria_checklist.map((c) => ({
            field: c.field,
            satisfied: c.satisfied,
            detail: c.detail,
          })),
        };
        // 如果评估通过，标记 State 为 SUCCEEDED
        if (payload.state_satisfied) {
          targetState.status = DAG_NODE_STATUS.SUCCEEDED;
          targetState.endedAtMs = Date.now();
          if (targetState.startedAtMs) {
            targetState.latencyMs = targetState.endedAtMs - targetState.startedAtMs;
          }
          recalcPlanStats(plan);
        }
      }
      return { activePlan: plan };
    });
  },

  /**
   * 处理 Plan 重构事件。
   * 做什么：用后端推送的全量 State 列表替换当前 Plan 的 states。
   * 为什么这样做：Plan 重构可能新增、修改或删除 State，需要全量替换。
   */
  onPlanReplanned: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      plan.status = 'replanning';

      // 保留已有 State 的 steps 和 nodes 数据，只更新元数据
      const newStates: DagStateProjection[] = payload.modified_states.map((s) => {
        const existing = findState(plan, s.state_id);
        if (existing) {
          // 更新元数据，保留执行数据
          existing.orderIndex = s.order_index;
          existing.intent = s.intent;
          existing.goal = s.goal;
          existing.completionCriteria = s.completion_criteria.map((c) => ({
            field: c.field,
            operator: c.operator,
            value: c.value,
          }));
          existing.dependsOn = s.depends_on;
          return existing;
        }
        // 新增的 State
        return {
          stateId: s.state_id,
          orderIndex: s.order_index,
          intent: s.intent,
          goal: s.goal,
          completionCriteria: s.completion_criteria.map((c) => ({
            field: c.field,
            operator: c.operator,
            value: c.value,
          })),
          dependsOn: s.depends_on,
          status: DAG_NODE_STATUS.PENDING,
          selectedSkills: [],
          steps: [],
          stepsCompleted: 0,
          stepsTotal: 0,
          nodesSucceeded: 0,
          nodesFailed: 0,
          errorMessages: [],
        };
      });

      plan.states = newStates;
      plan.planningReason = payload.replan_reason;
      recalcPlanStats(plan);

      return { activePlan: plan };
    });
  },

  /**
   * 处理 Plan 完成事件。
   * 做什么：标记 Plan 为 completed，记录结束时间，保存到历史。
   * 为什么这样做：前端需要展示执行摘要并标记 Plan 为完成态。
   */
  onPlanCompleted: (payload) => {
    const { activePlan, planHistory } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    const now = Date.now();
    set((state) => {
      const plan = { ...state.activePlan! };
      plan.status = 'completed';
      plan.endedAtMs = now;
      plan.completedStates = payload.succeeded_states;
      plan.failedStates = payload.failed_states;

      // 保存到历史
      const newHistory = { ...state.planHistory, [plan.planId]: plan };
      return { activePlan: plan, planHistory: newHistory };
    });
  },

  /**
   * 处理 Plan 终止事件。
   * 做什么：标记 Plan 为 terminated，记录终止原因，保存到历史。
   * 为什么这样做：前端需要展示终止原因并标记 Plan 为终止态。
   */
  onPlanTerminated: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      plan.status = 'terminated';
      plan.endedAtMs = Date.now();

      // 保存到历史
      const newHistory = { ...state.planHistory, [plan.planId]: plan };
      return { activePlan: plan, planHistory: newHistory };
    });
  },

  /**
   * 处理预算耗尽事件。
   * 做什么：更新 Plan 的预算消耗信息，标记状态为 budget_exhausted。
   * 为什么这样做：前端需要在全局面板展示预算警告。
   */
  onBudgetExhausted: (payload) => {
    const { activePlan } = get();
    if (!activePlan || activePlan.planId !== payload.plan_id) return;

    set((state) => {
      const plan = { ...state.activePlan! };
      plan.budgetConsumed.tool_calls = payload.consumed;
      plan.budgetLimit.max_total_tool_calls = payload.limit;
      if (payload.level === 'global') {
        plan.status = 'budget_exhausted';
      }
      return { activePlan: plan };
    });
  },

  // ============================================================
  // UI 操作方法
  // ============================================================

  /** 设置面板可见性 */
  setPanelVisible: (visible) => set({ isPanelVisible: visible }),

  /** 切换 State 容器展开/折叠 */
  toggleStateExpanded: (stateId) =>
    set((state) => ({
      expandedStates: {
        ...state.expandedStates,
        [stateId]: !state.expandedStates[stateId],
      },
    })),

  /** 切换 Step 容器展开/折叠 */
  toggleStepExpanded: (stepId) =>
    set((state) => ({
      expandedSteps: {
        ...state.expandedSteps,
        [stepId]: !state.expandedSteps[stepId],
      },
    })),

  /** 切换 Node 详情展开/折叠 */
  toggleNodeExpanded: (nodeId) =>
    set((state) => ({
      expandedNodes: {
        ...state.expandedNodes,
        [nodeId]: !state.expandedNodes[nodeId],
      },
    })),

  /** 设置搜索关键词 */
  setSearchQuery: (query) => set({ searchQuery: query }),

  /** 设置画布缩放比例（限制在 0.3 ~ 3.0 之间） */
  setCanvasZoom: (zoom) =>
    set({ canvasZoom: Math.min(3.0, Math.max(0.3, zoom)) }),

  /** 设置画布平移偏移 */
  setCanvasOffset: (offset) => set({ canvasOffset: offset }),

  /** 清除当前 Plan */
  clearPlan: () =>
    set({
      activePlan: null,
      isPanelVisible: false,
      expandedStates: {},
      expandedSteps: {},
      expandedNodes: {},
      searchQuery: '',
      canvasZoom: 1,
      canvasOffset: { x: 0, y: 0 },
    }),
}));
