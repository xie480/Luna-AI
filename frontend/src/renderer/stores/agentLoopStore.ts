/**
 * Agent Loop 工作流状态管理。
 *
 * 做什么：维护 Agent Loop 万能循环模式的投影数据，响应后端 SSE 事件驱动 UI 更新。
 * 为什么这样做：Agent Loop 的数据结构（Goal + Plan + StepLoop）与 Plan-State-Node 的
 *               四层嵌套完全不同，需要独立 Store 以避免污染 dagWorkflowStore。
 * 输入输出：由 SSEManager 调用事件处理方法，AgentLoopPanel 及子组件通过 selector 消费。
 * 边界条件：activeLoop 为 null 时不渲染面板。
 * 异常行为：无。
 */
import { create } from 'zustand';
import type {
  AgentLoopProjection,
  AgentStepProjection,
  AgentToolCall,
  AgentToolResult,
  AgentStepEvaluation,
  AgentBudgetState,
  AgentLoopIteration,
} from '../types/agentLoopWorkflow';

// ============================================================
// Store 状态接口
// ============================================================

interface AgentLoopStoreState {
  // === 核心数据 ===
  activeLoop: AgentLoopProjection | null;
  loopHistory: Record<string, AgentLoopProjection>;

  // === UI 展示状态 ===
  isPanelVisible: boolean;
  goalExpanded: boolean;
  expandedSteps: Record<string, boolean>;
  expandedThoughts: Record<string, boolean>;
  expandedObservations: Record<string, boolean>;
  expandedEvaluations: Record<string, boolean>;
  /** 循环迭代展开状态，key 为 `${stepId}_${iterationIndex}` */
  expandedIterations: Record<string, boolean>;

  // === 事件处理方法 ===
  onGoalLocked: (payload: Record<string, unknown>, traceId: string) => void;
  onPlanCreated: (payload: Record<string, unknown>, traceId: string) => void;
  onStepThinking: (payload: Record<string, unknown>) => void;
  onNodeStarted: (payload: Record<string, unknown>) => void;
  onNodeCompleted: (payload: Record<string, unknown>) => void;
  onStepObserved: (payload: Record<string, unknown>) => void;
  onStepEvaluated: (payload: Record<string, unknown>) => void;
  onStepRepaired: (payload: Record<string, unknown>) => void;
  onPlanReplanned: (payload: Record<string, unknown>) => void;
  onFinalVerified: (payload: Record<string, unknown>) => void;
  onPlanCompleted: (payload: Record<string, unknown>) => void;
  onPlanTerminated: (payload: Record<string, unknown>) => void;
  onBudgetExhausted: (payload: Record<string, unknown>) => void;

  // === UI 操作方法 ===
  setPanelVisible: (visible: boolean) => void;
  toggleGoalExpanded: () => void;
  toggleStepExpanded: (stepId: string) => void;
  toggleThoughtExpanded: (stepId: string) => void;
  toggleObservationExpanded: (stepId: string) => void;
  toggleEvaluationExpanded: (stepId: string) => void;
  /** 切换循环迭代展开/评估展开，suffix 为可选后缀（如 '_eval'） */
  toggleIterationExpanded: (stepId: string, iterationIndex: number, suffix?: string) => void;
  clearLoop: () => void;
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 按 stepId 查找步骤投影。
 */
function findStep(loop: AgentLoopProjection, stepId: string): AgentStepProjection | undefined {
  return loop.plan.steps.find((s) => s.stepId === stepId);
}

/**
 * 按 stepIndex 查找当前正在执行的步骤。
 */
function currentStep(loop: AgentLoopProjection): AgentStepProjection | undefined {
  if (loop.plan.currentStepIndex < loop.plan.steps.length) {
    return loop.plan.steps[loop.plan.currentStepIndex];
  }
  return undefined;
}

// ============================================================
// Store 实现
// ============================================================

export const useAgentLoopStore = create<AgentLoopStoreState>((set, get) => ({
  // === 核心数据初始值 ===
  activeLoop: null,
  loopHistory: {},

  // === UI 展示状态初始值 ===
  isPanelVisible: false,
  goalExpanded: true,
  expandedSteps: {},
  expandedThoughts: {},
  expandedObservations: {},
  expandedEvaluations: {},
  expandedIterations: {},

  // ============================================================
  // 事件处理方法
  // ============================================================

  /**
   * 处理目标锁定事件。
   * 做什么：创建 AgentLoopProjection 的初始结构。
   */
  onGoalLocked: (payload, traceId) => {
    const now = Date.now();
    const loop: AgentLoopProjection = {
      planId: (payload.task_id as string) || '',
      sessionId: '',
      traceId,
      status: 'goal_locking',
      chatMode: 'agent_loop',
      goal: {
        taskId: (payload.task_id as string) || '',
        globalGoal: (payload.global_goal as string) || '',
        goalDefinition: (payload.goal_definition as string) || '',
        acceptanceCriteria: (payload.acceptance_criteria as string[]) || [],
        nonGoals: (payload.non_goals as string[]) || [],
        constraints: (payload.constraints as string[]) || [],
        locked: true,
        lockedAtMs: now,
      },
      plan: {
        planVersion: 1,
        steps: [],
        currentStepIndex: 0,
        replanHistory: [],
      },
      budget: {
        tokenUsed: 0,
        toolCallsUsed: 0,
        stepRetriesUsed: 0,
        replanCount: 0,
        timeUsedMs: 0,
        maxToolCalls: 50,
        maxStepRetries: 3,
        maxReplanCount: 2,
        maxTimeMs: 300000,
      },
      startedAtMs: now,
    };
    set({ activeLoop: loop, isPanelVisible: true });
  },

  /**
   * 处理计划创建事件。
   * 做什么：将后端推送的步骤列表转换为前端投影。
   */
  onPlanCreated: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const states = (payload.states as Array<Record<string, unknown>>) || [];
      loop.plan = {
        ...loop.plan,
        steps: states.map((s, i) => ({
          stepId: (s.state_id as string) || `step_${i}`,
          title: (s.responsibility as string) || (s.intent as string) || `步骤 ${i + 1}`,
          intent: (s.intent as string) || '',
          dependencies: (s.depends_on as string[]) || [],
          expectedOutput: (s.goal as string) || '',
          status: 'pending' as const,
          riskNotes: '',
          rollbackHint: '',
          lastThought: '',
          toolCalls: [],
          toolResults: [],
          lastObservation: '',
          repairCount: 0,
          retryCount: 0,
          loopIterations: [],
          currentIterationIndex: 1,
        })),
        currentStepIndex: 0,
      };
      loop.status = 'executing';
      loop.planId = (payload.plan_id as string) || loop.planId;
      return { activeLoop: loop };
    });
  },

  /**
   * 处理步骤思考事件。
   * 做什么：更新当前步骤的思考结果，清空当前迭代的工具调用和结果（新迭代开始），
   *         同时根据 loopIterationIndex 更新当前循环迭代索引。
   * 为什么不从 payload.tool_calls 填充 toolCalls：
   *         工具调用列表由后续的 onNodeStarted 事件逐个构建，
   *         如果在此处也填充会导致同一个工具调用重复出现两次。
   */
  onStepThinking: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        const iterationIndex = (payload.loop_iteration_index as number) || step.currentIterationIndex || 1;
        updatedSteps[idx] = {
          ...step,
          status: 'running',
          lastThought: (payload.thought as string) || '',
          // 清空工具调用列表，由后续 onNodeStarted 事件逐个追加
          toolCalls: [],
          toolResults: [],
          lastObservation: '',
          evaluationResult: undefined,
          startedAtMs: step.startedAtMs || Date.now(),
          currentIterationIndex: iterationIndex,
        };
        loop.plan = { ...loop.plan, steps: updatedSteps };
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理节点启动事件。
   * 做什么：记录工具调用开始，包含完整的 purpose、parameters、skill_name 详情。
   */
  onNodeStarted: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        const toolCall: AgentToolCall = {
          toolName: (payload.tool_name as string) || '',
          skillName: (payload.skill_name as string) || '',
          parameters: (payload.parameters as Record<string, unknown>) || {},
          purpose: (payload.purpose as string) || '',
        };
        updatedSteps[idx] = {
          ...step,
          toolCalls: [...step.toolCalls, toolCall],
        };
        loop.plan = { ...loop.plan, steps: updatedSteps };
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理节点完成事件。
   * 做什么：记录工具执行结果，包含 tool_name 和单个工具调用耗时。
   */
  onNodeCompleted: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        const result: AgentToolResult = {
          nodeId: (payload.node_id as string) || '',
          toolName: (payload.tool_name as string) || (payload.node_type as string) || '',
          success: (payload.success as boolean) ?? true,
          toolOutput: JSON.stringify(payload.outputs || {}),
          errorMessage: (payload.error_message as string) || '',
          latencyMs: (payload.latency_ms as number) || 0,
          retryCount: (payload.retry_count as number) || 0,
        };
        updatedSteps[idx] = {
          ...step,
          toolResults: [...step.toolResults, result],
        };
        loop.plan = { ...loop.plan, steps: updatedSteps };
        // 更新预算
        loop.budget = {
          ...loop.budget,
          toolCallsUsed: loop.budget.toolCallsUsed + 1,
        };
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理观察事件。
   * 做什么：更新当前步骤的结构化观察。
   */
  onStepObserved: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        updatedSteps[idx] = {
          ...step,
          lastObservation: (payload.observation_preview as string) || '',
        };
        loop.plan = { ...loop.plan, steps: updatedSteps };
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理评估事件。
   * 做什么：更新当前步骤的评估结果，
   *         并将当前循环迭代快照保存到 loopIterations 历史中。
   *         评估完成后清空当前迭代的实时数据（已快照到 loopIterations），
   *         防止"循环迭代历史"和"当前活跃迭代"两个区块重复渲染相同的工具调用。
   */
  onStepEvaluated: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const stepIndex = payload.step_index as number;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        const verdict = payload.verdict as string;
        const evalResult: AgentStepEvaluation = {
          verdict: (verdict as AgentStepEvaluation['verdict']) || 'pass',
          evaluationReason: (payload.evaluation_reason as string) || '',
          gapAnalysis: (payload.gap_analysis as string) || '',
          suggestion: (payload.suggestion as string) || '',
          criteriaChecklist: [],
        };
        // 将当前迭代快照保存到 loopIterations 历史
        const iterationIndex = step.currentIterationIndex || (payload.loop_iteration_index as number) || 1;
        const iterationSnapshot: AgentLoopIteration = {
          iterationIndex,
          thought: step.lastThought,
          toolCalls: [...step.toolCalls],
          toolResults: [...step.toolResults],
          observation: step.lastObservation,
          evaluationResult: evalResult,
          startedAtMs: step.startedAtMs,
          endedAtMs: Date.now(),
          latencyMs: step.startedAtMs ? Date.now() - step.startedAtMs : undefined,
        };
        updatedSteps[idx] = {
          ...step,
          evaluationResult: evalResult,
          endedAtMs: verdict === 'pass' || verdict === 'partial' ? Date.now() : step.endedAtMs,
          latencyMs: step.startedAtMs ? Date.now() - step.startedAtMs : undefined,
          loopIterations: [...step.loopIterations, iterationSnapshot],
          // 清空当前迭代的实时数据，防止与 loopIterations 历史重复渲染
          // 数据已通过 iterationSnapshot 完整保存在 loopIterations 中
          lastThought: '',
          toolCalls: [],
          toolResults: [],
          lastObservation: '',
        };
        // 如果通过，推进到下一步
        if (verdict === 'pass' || verdict === 'partial') {
          updatedSteps[idx].status = 'passed';
          loop.plan = {
            ...loop.plan,
            steps: updatedSteps,
            currentStepIndex: (stepIndex ?? loop.plan.currentStepIndex) + 1,
          };
        } else {
          loop.plan = { ...loop.plan, steps: updatedSteps };
        }
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理修复事件。
   * 做什么：递增当前步骤的修复和重试计数，清空当前迭代的实时数据准备重新思考。
   * 注意：loopIterations 历史已经在 onStepEvaluated 中保存，此处无需再快照。
   */
  onStepRepaired: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const stepId = payload.step_id as string;
      const step = findStep(loop, stepId);
      if (step) {
        const idx = loop.plan.steps.indexOf(step);
        const updatedSteps = [...loop.plan.steps];
        updatedSteps[idx] = {
          ...step,
          repairCount: (payload.repair_count as number) || step.repairCount + 1,
          retryCount: (payload.retry_count as number) || step.retryCount + 1,
          lastThought: '',  // 清空思考，准备重新思考
          toolCalls: [],    // 清空工具调用，准备重新规划
          toolResults: [],
          lastObservation: '',
          evaluationResult: undefined,
          currentIterationIndex: (payload.repair_count as number) || step.repairCount + 1,
        };
        loop.plan = { ...loop.plan, steps: updatedSteps };
        loop.budget = {
          ...loop.budget,
          stepRetriesUsed: loop.budget.stepRetriesUsed + 1,
        };
      }
      return { activeLoop: loop };
    });
  },

  /**
   * 处理重规划事件。
   * 做什么：替换整个计划步骤列表。
   */
  onPlanReplanned: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const modifiedStates = (payload.modified_states as Array<Record<string, unknown>>) || [];
      const newVersion = (payload.plan_version as number) || loop.plan.planVersion + 1;
      const newSteps: AgentStepProjection[] = modifiedStates.map((s, i) => ({
        stepId: (s.state_id as string) || `step_${i}`,
        title: (s.responsibility as string) || `步骤 ${i + 1}`,
        intent: (s.intent as string) || '',
        dependencies: [],
        expectedOutput: (s.goal as string) || '',
        status: 'pending' as const,
        riskNotes: '',
        rollbackHint: '',
        lastThought: '',
        toolCalls: [],
        toolResults: [],
        lastObservation: '',
        repairCount: 0,
        retryCount: 0,
        loopIterations: [],
        currentIterationIndex: 1,
      }));
      loop.plan = {
        planVersion: newVersion,
        steps: newSteps,
        currentStepIndex: 0,
        replanHistory: [
          ...loop.plan.replanHistory,
          {
            fromVersion: loop.plan.planVersion,
            toVersion: newVersion,
            reason: (payload.replan_reason as string) || '',
            failedStepId: '',
            changedStepIds: newSteps.map((s) => s.stepId),
            timestampMs: Date.now(),
          },
        ],
      };
      loop.status = 'replanning';
      loop.budget = { ...loop.budget, replanCount: loop.budget.replanCount + 1 };
      return { activeLoop: loop };
    });
  },

  /**
   * 处理最终验收事件。
   *
   * 做什么：将后端推送的最终验收结果映射为前端投影。
   *         无论 pass/fail，整体循环状态都设为 'verifying'，
   *         因为后续仍有主 Chat LLM 汇总节点需要执行。
   *         前端渲染 AgentFinalVerifyCard 时根据 status 显示
   *         'pass'（绿色"通过"）或 'fail'（红色"失败"）。
   */
  onFinalVerified: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      const verificationStatus = (payload.verification_status as string) || 'pass';
      const allMet = payload.all_criteria_met as boolean;
      // 标准化为二值：pass=通过，fail=失败
      const normalizedStatus: 'pass' | 'fail' = verificationStatus === 'pass' ? 'pass' : 'fail';
      loop.finalVerification = {
        status: normalizedStatus,
        report: (payload.report_preview as string) || '',
        allCriteriaMet: allMet ?? (normalizedStatus === 'pass'),
        criteriaVerification: [],
      };
      // 无论 pass 还是 fail，整体循环状态都设为 verifying，
      // 因为后续仍有主 Chat LLM 汇总节点需要执行
      loop.status = 'verifying';
      return { activeLoop: loop };
    });
  },

  /**
   * 处理计划完成事件。
   */
  onPlanCompleted: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      loop.status = 'completed';
      loop.endedAtMs = Date.now();
      loop.elapsedMs = (payload.elapsed_ms as number) || (loop.endedAtMs - loop.startedAtMs);
      return { activeLoop: loop, loopHistory: { ...state.loopHistory, [loop.planId]: loop } };
    });
  },

  /**
   * 处理计划终止事件。
   */
  onPlanTerminated: (payload) => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      loop.status = 'terminated';
      loop.endedAtMs = Date.now();
      loop.elapsedMs = loop.endedAtMs - loop.startedAtMs;
      return { activeLoop: loop, loopHistory: { ...state.loopHistory, [loop.planId]: loop } };
    });
  },

  /**
   * 处理预算耗尽事件。
   */
  onBudgetExhausted: () => {
    set((state) => {
      if (!state.activeLoop) return state;
      const loop = { ...state.activeLoop };
      loop.status = 'budget_exhausted';
      return { activeLoop: loop };
    });
  },

  // ============================================================
  // UI 操作方法
  // ============================================================

  setPanelVisible: (visible) => set({ isPanelVisible: visible }),
  toggleGoalExpanded: () => set((state) => ({ goalExpanded: !state.goalExpanded })),
  toggleStepExpanded: (stepId) =>
    set((state) => ({ expandedSteps: { ...state.expandedSteps, [stepId]: !state.expandedSteps[stepId] } })),
  toggleThoughtExpanded: (stepId) =>
    set((state) => ({ expandedThoughts: { ...state.expandedThoughts, [stepId]: !state.expandedThoughts[stepId] } })),
  toggleObservationExpanded: (stepId) =>
    set((state) => ({ expandedObservations: { ...state.expandedObservations, [stepId]: !state.expandedObservations[stepId] } })),
  toggleEvaluationExpanded: (stepId) =>
    set((state) => ({ expandedEvaluations: { ...state.expandedEvaluations, [stepId]: !state.expandedEvaluations[stepId] } })),
  /** 切换循环迭代展开/评估展开。suffix 用于区分迭代本身展开（无后缀）和评估展开（'_eval' 后缀）。 */
  toggleIterationExpanded: (stepId, iterationIndex, suffix) =>
    set((state) => {
      const key = `${stepId}_${iterationIndex}${suffix || ''}`;
      return { expandedIterations: { ...state.expandedIterations, [key]: !state.expandedIterations[key] } };
    }),
  clearLoop: () => set({ activeLoop: null, isPanelVisible: false, expandedSteps: {}, expandedThoughts: {}, expandedObservations: {}, expandedEvaluations: {}, expandedIterations: {} }),
}));
