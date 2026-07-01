/**
 * Phase 10：任务状态管理 Store 单元测试。
 * 做什么：测试 taskStateStore 的核心逻辑，包括状态迁移、按钮启用条件、命令发送等。
 * 为什么这样做：确保任务状态机在前端侧的正确性，特别是状态迁移和按钮启用条件。
 * 覆盖范围：
 *   1. 状态初始化（无活跃任务）
 *   2. SSE 事件处理（暂停/恢复/超时/恢复启动/恢复完成/恢复失败）
 *   3. 任务状态设置与清除
 *   4. 按钮启用条件（可取消/可暂停/可恢复）
 *   5. 未完成任务设置
 *   6. 边界条件：null 任务状态、非法状态序列
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useTaskStateStore, TASK_STATUS_LABEL } from '../../src/renderer/stores/taskStateStore';
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
// 辅助函数：重置 Store 状态
// ============================================================
function resetStore(): void {
  useTaskStateStore.getState().clearTaskState();
}

describe('taskStateStore — 任务状态管理 Store', () => {
  beforeEach(() => {
    resetStore();
  });

  // ============================================================
  // 1. 状态初始化
  // ============================================================
  describe('状态初始化', () => {
    it('初始状态应为 null', () => {
      const state = useTaskStateStore.getState();
      expect(state.taskId).toBeNull();
      expect(state.taskStatus).toBeNull();
      expect(state.planId).toBeNull();
      expect(state.pausedInfo).toBeNull();
      expect(state.cancelInfo).toBeNull();
      expect(state.recoveryInfo).toBeNull();
      expect(state.unfinishedTasks).toEqual([]);
      expect(state.isRecoveryDialogOpen).toBe(false);
    });

    it('按钮启用条件在初始状态下应全部返回 false', () => {
      const state = useTaskStateStore.getState();
      expect(state.isCancellable()).toBe(false);
      expect(state.isPausable()).toBe(false);
      expect(state.isResumable()).toBe(false);
    });
  });

  // ============================================================
  // 2. 任务状态设置与清除
  // ============================================================
  describe('setTaskState / clearTaskState', () => {
    it('设置任务状态后应正确反映状态', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');

      const updated = useTaskStateStore.getState();
      expect(updated.taskId).toBe('task-001');
      expect(updated.taskStatus).toBe('RUNNING');
      expect(updated.planId).toBe('plan-001');
    });

    it('清除任务状态后应重置为初始值', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');
      store.clearTaskState();

      const cleared = useTaskStateStore.getState();
      expect(cleared.taskId).toBeNull();
      expect(cleared.taskStatus).toBeNull();
      expect(cleared.planId).toBeNull();
      expect(cleared.pausedInfo).toBeNull();
      expect(cleared.recoveryInfo).toBeNull();
      expect(cleared.unfinishedTasks).toEqual([]);
      expect(cleared.isRecoveryDialogOpen).toBe(false);
    });

    it('可不传 planId 设置任务状态', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING');

      const updated = useTaskStateStore.getState();
      expect(updated.taskId).toBe('task-001');
      expect(updated.planId).toBeNull();
    });
  });

  // ============================================================
  // 3. SSE 事件处理
  // ============================================================
  describe('onTaskPaused — 任务暂停事件', () => {
    it('应正确标记为 PAUSED', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');

      const payload: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '用户手动暂停',
        is_emotion_freeze: false,
        paused_at_ms: Date.now(),
      };
      store.onTaskPaused(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('PAUSED');
      expect(updated.pausedInfo).not.toBeNull();
      expect(updated.pausedInfo!.reason).toBe('用户手动暂停');
      expect(updated.pausedInfo!.isEmotionFreeze).toBe(false);
    });

    it('情绪冻结时应标记 isEmotionFreeze 为 true', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');

      const payload: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '情绪冻结',
        is_emotion_freeze: true,
        paused_at_ms: Date.now(),
      };
      store.onTaskPaused(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.pausedInfo!.isEmotionFreeze).toBe(true);
    });

    it('is_emotion_freeze 默认为 false', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');

      const payload: TaskPausedPayload = {
        task_id: 'task-001',
        reason: '用户暂停',
        paused_at_ms: Date.now(),
      };
      store.onTaskPaused(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.pausedInfo!.isEmotionFreeze).toBe(false);
    });
  });

  describe('onTaskResumed — 任务恢复事件', () => {
    it('应清除暂停信息并将状态恢复为 RUNNING', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'PAUSED', 'plan-001');
      store.onTaskPaused({
        task_id: 'task-001',
        reason: '用户暂停',
        paused_at_ms: Date.now(),
      });

      const payload: TaskResumedPayload = {
        task_id: 'task-001',
        dag_state_snapshot: {},
      };
      store.onTaskResumed(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('RUNNING');
      expect(updated.pausedInfo).toBeNull();
      expect(updated.recoveryInfo).toBeNull();
    });
  });

  describe('onTaskTimeout — 任务超时事件', () => {
    it('应标记为 TIMED_OUT', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'RUNNING', 'plan-001');

      const payload: TaskTimeoutPayload = {
        task_id: 'task-001',
        timeout_seconds: 300,
        terminated_states: 2,
      };
      store.onTaskTimeout(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('TIMED_OUT');
    });
  });

  describe('onRecoveryStarted — 恢复启动事件', () => {
    it('应标记为 RECOVERING', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'TIMED_OUT', 'plan-001');

      const payload: TaskRecoveryStartedPayload = {
        task_id: 'task-001',
        snapshot_version: 3,
      };
      store.onRecoveryStarted(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('RECOVERING');
      expect(updated.recoveryInfo).not.toBeNull();
      expect(updated.recoveryInfo!.snapshotVersion).toBe(3);
    });
  });

  describe('onRecoveryCompleted — 恢复完成事件', () => {
    it('应恢复为 RUNNING 并保留恢复信息', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'TIMED_OUT', 'plan-001');
      store.onRecoveryStarted({
        task_id: 'task-001',
        snapshot_version: 3,
      });

      const payload: TaskRecoveryCompletedPayload = {
        task_id: 'task-001',
        recovered_cursor: 2,
        recovered_states: 3,
      };
      store.onRecoveryCompleted(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('RUNNING');
      expect(updated.recoveryInfo).not.toBeNull();
      expect(updated.recoveryInfo!.snapshotVersion).toBe(3);
    });
  });

  describe('onRecoveryFailed — 恢复失败事件', () => {
    it('应标记为 TERMINATED 并清除恢复信息', () => {
      const store = useTaskStateStore.getState();
      store.setTaskState('task-001', 'TIMED_OUT', 'plan-001');
      store.onRecoveryStarted({
        task_id: 'task-001',
        snapshot_version: 3,
      });

      const payload: TaskRecoveryFailedPayload = {
        task_id: 'task-001',
        reason: '快照损坏',
      };
      store.onRecoveryFailed(payload);

      const updated = useTaskStateStore.getState();
      expect(updated.taskStatus).toBe('TERMINATED');
      expect(updated.recoveryInfo).toBeNull();
    });
  });

  // ============================================================
  // 4. 按钮启用条件
  // ============================================================
  describe('isCancellable — 取消按钮启用条件', () => {
    it('RUNNING 状态应可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'RUNNING');
      expect(useTaskStateStore.getState().isCancellable()).toBe(true);
    });

    it('PAUSED 状态应可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'PAUSED');
      expect(useTaskStateStore.getState().isCancellable()).toBe(true);
    });

    it('GATING_SUSPENDED 状态应可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'GATING_SUSPENDED');
      expect(useTaskStateStore.getState().isCancellable()).toBe(true);
    });

    it('TIMED_OUT 状态应可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'TIMED_OUT');
      expect(useTaskStateStore.getState().isCancellable()).toBe(true);
    });

    it('SUCCEEDED 状态应不可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'SUCCEEDED');
      expect(useTaskStateStore.getState().isCancellable()).toBe(false);
    });

    it('RECOVERING 状态应不可取消', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'RECOVERING');
      expect(useTaskStateStore.getState().isCancellable()).toBe(false);
    });

    it('null 状态应不可取消', () => {
      expect(useTaskStateStore.getState().isCancellable()).toBe(false);
    });
  });

  describe('isPausable — 暂停按钮启用条件', () => {
    it('RUNNING 状态应可暂停', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'RUNNING');
      expect(useTaskStateStore.getState().isPausable()).toBe(true);
    });

    it('GATING_SUSPENDED 状态应可暂停', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'GATING_SUSPENDED');
      expect(useTaskStateStore.getState().isPausable()).toBe(true);
    });

    it('PAUSED 状态应不可暂停', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'PAUSED');
      expect(useTaskStateStore.getState().isPausable()).toBe(false);
    });

    it('TIMED_OUT 状态应不可暂停', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'TIMED_OUT');
      expect(useTaskStateStore.getState().isPausable()).toBe(false);
    });

    it('SUCCEEDED 状态应不可暂停', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'SUCCEEDED');
      expect(useTaskStateStore.getState().isPausable()).toBe(false);
    });
  });

  describe('isResumable — 恢复按钮启用条件', () => {
    it('PAUSED 状态应可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'PAUSED');
      expect(useTaskStateStore.getState().isResumable()).toBe(true);
    });

    it('TIMED_OUT 状态应可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'TIMED_OUT');
      expect(useTaskStateStore.getState().isResumable()).toBe(true);
    });

    it('RECOVERING 状态应可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'RECOVERING');
      expect(useTaskStateStore.getState().isResumable()).toBe(true);
    });

    it('RUNNING 状态应不可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'RUNNING');
      expect(useTaskStateStore.getState().isResumable()).toBe(false);
    });

    it('SUCCEEDED 状态应不可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'SUCCEEDED');
      expect(useTaskStateStore.getState().isResumable()).toBe(false);
    });

    it('TERMINATED 状态应不可恢复', () => {
      useTaskStateStore.getState().setTaskState('task-001', 'TERMINATED');
      expect(useTaskStateStore.getState().isResumable()).toBe(false);
    });
  });

  // ============================================================
  // 5. 未完成任务设置
  // ============================================================
  describe('setUnfinishedTasks — 未完成任务设置', () => {
    it('设置未完成任务后应自动打开恢复弹窗', () => {
      const tasks: UnfinishedTask[] = [{
        taskId: 'task-001',
        taskStatus: 'RUNNING',
        planId: 'plan-001',
        createdAtMs: Date.now() - 60000,
        savedAtMs: Date.now(),
        cursor: 2,
        totalStates: 5,
        snapshotVersion: 2,
        triggerEvent: 'system_crash',
      }];

      useTaskStateStore.getState().setUnfinishedTasks(tasks);

      const updated = useTaskStateStore.getState();
      expect(updated.unfinishedTasks).toHaveLength(1);
      expect(updated.isRecoveryDialogOpen).toBe(true);
      expect(updated.unfinishedTasks[0].taskId).toBe('task-001');
    });

    it('空列表时应关闭恢复弹窗', () => {
      useTaskStateStore.getState().setUnfinishedTasks([]);

      const updated = useTaskStateStore.getState();
      expect(updated.unfinishedTasks).toHaveLength(0);
      expect(updated.isRecoveryDialogOpen).toBe(false);
    });
  });

  // ============================================================
  // 6. TASK_STATUS_LABEL 映射完整性
  // ============================================================
  describe('TASK_STATUS_LABEL 标签映射', () => {
    it('所有任务状态都有中文标签', () => {
      const expectedStatuses = [
        'CREATED', 'PLANNING', 'PLAN_READY', 'RUNNING',
        'PAUSED', 'PENDING_APPROVAL', 'DEGRADED', 'GATING_SUSPENDED',
        'SUCCEEDED', 'FAILED', 'TERMINATED', 'TIMED_OUT',
        'BUDGET_EXHAUSTED', 'RECOVERING', 'SNAPSHOT_RESTORED',
      ];
      for (const status of expectedStatuses) {
        expect(TASK_STATUS_LABEL[status as keyof typeof TASK_STATUS_LABEL]).toBeDefined();
        expect(TASK_STATUS_LABEL[status as keyof typeof TASK_STATUS_LABEL]).toBeTruthy();
      }
    });

    it('标签应为中文', () => {
      expect(TASK_STATUS_LABEL.RUNNING).toBe('执行中');
      expect(TASK_STATUS_LABEL.PAUSED).toBe('已暂停');
      expect(TASK_STATUS_LABEL.TIMED_OUT).toBe('已超时');
      expect(TASK_STATUS_LABEL.RECOVERING).toBe('恢复中');
      expect(TASK_STATUS_LABEL.TERMINATED).toBe('已终止');
      expect(TASK_STATUS_LABEL.SUCCEEDED).toBe('已完成');
    });
  });
});
