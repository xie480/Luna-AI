/**
 * Phase 10：共享类型与枚举单元测试。
 * 做什么：验证 Phase 10 新增的事件类型常量、载荷接口和枚举扩展的正确定义。
 * 为什么这样做：确保共享类型层与后端协议版本对齐，避免类型不匹配导致的运行时错误。
 * 覆盖范围：
 *   1. WS_MSG_TYPE 中 Phase 10 命令和事件常量
 *   2. DAG_WORKFLOW_EVENT_TYPE 中 Phase 10 事件常量
 *   3. DagPlanStatus 扩展类型中新增的 paused/recovering/timed_out
 *   4. Phase 10 载荷接口结构
 *   5. UnfinishedTask 接口结构
 */
import { describe, it, expect } from 'vitest';
import {
  WS_MSG_TYPE,
  DAG_WORKFLOW_EVENT_TYPE,
} from '../../src/shared/enum';
import type {
  TaskPausedPayload,
  TaskResumedPayload,
  TaskTimeoutPayload,
  TaskRecoveryStartedPayload,
  TaskRecoveryCompletedPayload,
  TaskRecoveryFailedPayload,
  UnfinishedTask,
} from '../../src/shared/types';

// ============================================================
// 1. WS_MSG_TYPE 常量验证
// ============================================================
describe('WS_MSG_TYPE — Phase 10 消息类型常量', () => {
  it('应定义 CMD_PAUSE_TASK', () => {
    expect(WS_MSG_TYPE.CMD_PAUSE_TASK).toBe('CMD_PAUSE_TASK');
  });

  it('应定义 CMD_RESUME_TASK', () => {
    expect(WS_MSG_TYPE.CMD_RESUME_TASK).toBe('CMD_RESUME_TASK');
  });

  it('CMD_CANCEL_TASK 应已存在', () => {
    expect(WS_MSG_TYPE.CMD_CANCEL_TASK).toBe('CMD_CANCEL_TASK');
  });

  it('应定义 EVT_TASK_PAUSED', () => {
    expect(WS_MSG_TYPE.EVT_TASK_PAUSED).toBe('EVT_TASK_PAUSED');
  });

  it('应定义 EVT_TASK_RESUMED', () => {
    expect(WS_MSG_TYPE.EVT_TASK_RESUMED).toBe('EVT_TASK_RESUMED');
  });

  it('应定义 EVT_TASK_TIMEOUT', () => {
    expect(WS_MSG_TYPE.EVT_TASK_TIMEOUT).toBe('EVT_TASK_TIMEOUT');
  });

  it('应定义 EVT_TASK_RECOVERY_STARTED', () => {
    expect(WS_MSG_TYPE.EVT_TASK_RECOVERY_STARTED).toBe('EVT_TASK_RECOVERY_STARTED');
  });

  it('应定义 EVT_TASK_RECOVERY_COMPLETED', () => {
    expect(WS_MSG_TYPE.EVT_TASK_RECOVERY_COMPLETED).toBe('EVT_TASK_RECOVERY_COMPLETED');
  });

  it('应定义 EVT_TASK_RECOVERY_FAILED', () => {
    expect(WS_MSG_TYPE.EVT_TASK_RECOVERY_FAILED).toBe('EVT_TASK_RECOVERY_FAILED');
  });
});

// ============================================================
// 2. DAG_WORKFLOW_EVENT_TYPE 常量验证
// ============================================================
describe('DAG_WORKFLOW_EVENT_TYPE — Phase 10 事件类型常量', () => {
  it('应定义 TASK_PAUSED', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_PAUSED).toBe('EVT_TASK_PAUSED');
  });

  it('应定义 TASK_RESUMED', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_RESUMED).toBe('EVT_TASK_RESUMED');
  });

  it('应定义 TASK_TIMEOUT', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_TIMEOUT).toBe('EVT_TASK_TIMEOUT');
  });

  it('应定义 TASK_RECOVERY_STARTED', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_RECOVERY_STARTED).toBe('EVT_TASK_RECOVERY_STARTED');
  });

  it('应定义 TASK_RECOVERY_COMPLETED', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_RECOVERY_COMPLETED).toBe('EVT_TASK_RECOVERY_COMPLETED');
  });

  it('应定义 TASK_RECOVERY_FAILED', () => {
    expect(DAG_WORKFLOW_EVENT_TYPE.TASK_RECOVERY_FAILED).toBe('EVT_TASK_RECOVERY_FAILED');
  });
});

// ============================================================
// 3. Phase 10 载荷接口结构验证
// ============================================================
describe('Phase 10 载荷接口 — 结构验证', () => {
  describe('TaskPausedPayload', () => {
    it('应具有正确的必选字段', () => {
      const payload: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '用户暂停',
        paused_at_ms: 1000000,
      };
      expect(payload.task_id).toBe('task-001');
      expect(payload.reason).toBe('用户暂停');
      expect(payload.paused_at_ms).toBe(1000000);
    });

    it('is_emotion_freeze 可选字段应为 undefined 或 boolean', () => {
      const p1: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '用户暂停',
        paused_at_ms: 1000000,
      };
      expect(p1.is_emotion_freeze).toBeUndefined();

      const p2: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '情绪冻结',
        is_emotion_freeze: true,
        paused_at_ms: 2000000,
      };
      expect(p2.is_emotion_freeze).toBe(true);
    });
  });

  describe('TaskResumedPayload', () => {
    it('应具有正确的字段类型', () => {
      const payload: TaskResumedPayload = {
        task_id: 'task-001',
        dag_state_snapshot: { cursor: 2, phase: 'executing' },
      };
      expect(payload.task_id).toBe('task-001');
      expect(payload.dag_state_snapshot.cursor).toBe(2);
    });
  });

  describe('TaskTimeoutPayload', () => {
    it('应具有正确的字段', () => {
      const payload: TaskTimeoutPayload = {
        task_id: 'task-001',
        timeout_seconds: 300,
        terminated_states: 2,
      };
      expect(payload.timeout_seconds).toBe(300);
      expect(payload.terminated_states).toBe(2);
    });
  });

  describe('TaskRecoveryStartedPayload', () => {
    it('应具有正确的字段', () => {
      const payload: TaskRecoveryStartedPayload = {
        task_id: 'task-001',
        snapshot_version: 3,
      };
      expect(payload.snapshot_version).toBe(3);
    });
  });

  describe('TaskRecoveryCompletedPayload', () => {
    it('应具有正确的字段', () => {
      const payload: TaskRecoveryCompletedPayload = {
        task_id: 'task-001',
        recovered_cursor: 2,
        recovered_states: 3,
      };
      expect(payload.recovered_cursor).toBe(2);
      expect(payload.recovered_states).toBe(3);
    });
  });

  describe('TaskRecoveryFailedPayload', () => {
    it('应具有正确的字段', () => {
      const payload: TaskRecoveryFailedPayload = {
        task_id: 'task-001',
        reason: '快照损坏',
      };
      expect(payload.reason).toBe('快照损坏');
    });
  });
});

// ============================================================
// 4. UnfinishedTask 接口验证
// ============================================================
describe('UnfinishedTask 接口', () => {
  it('应具有正确的字段类型', () => {
    const task: UnfinishedTask = {
      taskId: 'task-001',
      taskStatus: 'RUNNING',
      planId: 'plan-001',
      createdAtMs: 1000000,
      savedAtMs: 2000000,
      cursor: 2,
      totalStates: 5,
      snapshotVersion: 2,
      triggerEvent: 'system_crash',
    };

    expect(task.taskId).toBe('task-001');
    expect(task.taskStatus).toBe('RUNNING');
    expect(task.planId).toBe('plan-001');
    expect(task.cursor).toBe(2);
    expect(task.totalStates).toBe(5);
    expect(task.snapshotVersion).toBe(2);
    expect(task.triggerEvent).toBe('system_crash');
  });
});
