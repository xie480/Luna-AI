/**
 * Phase 10：dagWorkflow 类型与 dagWorkflowStore 扩展单元测试。
 * 做什么：验证 DagPlanStatus 新增状态值和 dagWorkflowStore 的 onPlanStatusChange 方法。
 * 为什么这样做：确保 Plan 级状态与任务级状态的联动正确性。
 * 覆盖范围：
 *   1. DagPlanStatus 新增的 paused/recovering/timed_out 枚举值
 *   2. DAG_PLAN_STATUS_LABEL 扩展
 *   3. dagWorkflowStore.onPlanStatusChange 方法
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  DAG_PLAN_STATUS_LABEL,
  type DagPlanStatus,
} from '../../../src/renderer/types/dagWorkflow';
import { useDagWorkflowStore } from '../../../src/renderer/stores/dagWorkflowStore';

describe('DagPlanStatus — Phase 10 扩展', () => {
  describe('新增枚举值', () => {
    it('应支持 paused 状态', () => {
      const status: DagPlanStatus = 'paused';
      expect(status).toBe('paused');
    });

    it('应支持 recovering 状态', () => {
      const status: DagPlanStatus = 'recovering';
      expect(status).toBe('recovering');
    });

    it('应支持 timed_out 状态', () => {
      const status: DagPlanStatus = 'timed_out';
      expect(status).toBe('timed_out');
    });

    it('原有状态应保持不变', () => {
      const statuses: DagPlanStatus[] = [
        'planning', 'executing', 'replanning',
        'completed', 'terminated', 'budget_exhausted',
      ];
      expect(statuses).toHaveLength(6);
    });
  });

  describe('DAG_PLAN_STATUS_LABEL 中文标签映射', () => {
    it('paused 标签应为"已暂停"', () => {
      expect(DAG_PLAN_STATUS_LABEL.paused).toBe('已暂停');
    });

    it('recovering 标签应为"恢复中"', () => {
      expect(DAG_PLAN_STATUS_LABEL.recovering).toBe('恢复中');
    });

    it('timed_out 标签应为"已超时"', () => {
      expect(DAG_PLAN_STATUS_LABEL.timed_out).toBe('已超时');
    });

    it('原有标签不应受影响', () => {
      expect(DAG_PLAN_STATUS_LABEL.executing).toBe('执行中');
      expect(DAG_PLAN_STATUS_LABEL.completed).toBe('已完成');
      expect(DAG_PLAN_STATUS_LABEL.terminated).toBe('已终止');
    });
  });
});

describe('dagWorkflowStore — onPlanStatusChange Phase 10 扩展', () => {
  beforeEach(() => {
    useDagWorkflowStore.getState().clearPlan();
  });

  it('应正确修改 Plan 状态为 paused', () => {
    // 先设置一个激活的 Plan
    const store = useDagWorkflowStore.getState();
    store.onPlanCreated({
      plan_id: 'plan-001',
      session_id: 'sess-001',
      trace_id: 'trace-001',
      interaction_id: 'interaction-001',
      assistant_message_id: 'msg-001',
      global_objective: {
        overall_goal: '测试目标',
        success_criteria: '成功标准',
        output_format: 'json',
        constraints: [],
      },
      states: [],
      chat_mode: 'plan_state_node',
      planning_reason: '测试',
      budget_limit: { max_total_tool_calls: 50 },
    } as any, 'trace-001');

    // 修改为 paused
    useDagWorkflowStore.getState().onPlanStatusChange('paused');
    expect(useDagWorkflowStore.getState().activePlan?.status).toBe('paused');
  });

  it('应正确修改 Plan 状态为 recovering', () => {
    const store = useDagWorkflowStore.getState();
    store.onPlanCreated({
      plan_id: 'plan-001',
      session_id: 'sess-001',
      trace_id: 'trace-001',
      interaction_id: 'interaction-001',
      assistant_message_id: 'msg-001',
      global_objective: {
        overall_goal: '测试目标',
        success_criteria: '成功标准',
        output_format: 'json',
        constraints: [],
      },
      states: [],
      chat_mode: 'plan_state_node',
      planning_reason: '测试',
      budget_limit: { max_total_tool_calls: 50 },
    } as any, 'trace-001');

    useDagWorkflowStore.getState().onPlanStatusChange('recovering');
    expect(useDagWorkflowStore.getState().activePlan?.status).toBe('recovering');
  });

  it('应正确修改 Plan 状态为 timed_out', () => {
    const store = useDagWorkflowStore.getState();
    store.onPlanCreated({
      plan_id: 'plan-001',
      session_id: 'sess-001',
      trace_id: 'trace-001',
      interaction_id: 'interaction-001',
      assistant_message_id: 'msg-001',
      global_objective: {
        overall_goal: '测试目标',
        success_criteria: '成功标准',
        output_format: 'json',
        constraints: [],
      },
      states: [],
      chat_mode: 'plan_state_node',
      planning_reason: '测试',
      budget_limit: { max_total_tool_calls: 50 },
    } as any, 'trace-001');

    useDagWorkflowStore.getState().onPlanStatusChange('timed_out');
    expect(useDagWorkflowStore.getState().activePlan?.status).toBe('timed_out');
  });

  it('activePlan 为 null 时 onPlanStatusChange 应无操作', () => {
    expect(useDagWorkflowStore.getState().activePlan).toBeNull();
    useDagWorkflowStore.getState().onPlanStatusChange('paused');
    expect(useDagWorkflowStore.getState().activePlan).toBeNull();
  });
});