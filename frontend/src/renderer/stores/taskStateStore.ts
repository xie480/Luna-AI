/**
 * Phase 10：任务状态机与中断恢复 — 任务状态管理 Store。
 * 做什么：维护任务级生命周期状态，响应后端 SSE 事件驱动 UI 更新，
 *         提供用户主动操作（取消、暂停、恢复）的 WebSocket 命令发送。
 * 为什么这样做：Phase 10 引入任务级生命周期（暂停/恢复/超时/崩溃恢复），
 *               需要独立 Store 隔离任务级状态与 DAG 展示级状态，避免污染 dagWorkflowStore。
 * 输入输出：由 SSEManager 调用事件处理方法，TaskControlBar 及 DagGlobalInfoBar 通过 selector 消费。
 * 边界条件：taskId 为 null 时意味着当前没有活跃任务。
 * 异常行为：无。
 */
import { create } from 'zustand';
import { AI_SERVICE_BASE_URL } from '../appConfig';
import type {
  TaskPausedPayload,
  TaskResumedPayload,
  TaskTimeoutPayload,
  TaskRecoveryStartedPayload,
  TaskRecoveryCompletedPayload,
  TaskRecoveryFailedPayload,
  UnfinishedTask,
} from '../../shared/types';

// ============================================================
// 任务状态类型定义（与后端 TaskStatus 一致）
// ============================================================

/**
 * 任务状态枚举。
 * 做什么：定义任务级生命周期的全部可能状态。
 * 为什么这样做：与后端 TaskStatus 枚举严格对齐，前端 UI 按状态决定按钮启用/禁用与布局。
 * 边界条件：null 表示无活跃任务。
 */
export type TaskStatus =
  | 'CREATED'
  | 'PLANNING'
  | 'PLAN_READY'
  | 'RUNNING'
  | 'PAUSED'
  | 'PENDING_APPROVAL'
  | 'DEGRADED'
  | 'GATING_SUSPENDED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'TERMINATED'
  | 'TIMED_OUT'
  | 'BUDGET_EXHAUSTED'
  | 'RECOVERING'
  | 'SNAPSHOT_RESTORED';

/**
 * 任务状态中文标签映射。
 * 做什么：将英文状态映射为中文展示文案。
 */
export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  CREATED: '已创建',
  PLANNING: '规划中',
  PLAN_READY: '规划就绪',
  RUNNING: '执行中',
  PAUSED: '已暂停',
  PENDING_APPROVAL: '待审批',
  DEGRADED: '降级运行',
  GATING_SUSPENDED: '审批挂起',
  SUCCEEDED: '已完成',
  FAILED: '执行失败',
  TERMINATED: '已终止',
  TIMED_OUT: '已超时',
  BUDGET_EXHAUSTED: '预算耗尽',
  RECOVERING: '恢复中',
  SNAPSHOT_RESTORED: '快照已恢复',
};

// ============================================================
// Store 状态接口
// ============================================================

/**
 * 任务状态 Store 状态接口。
 * 做什么：定义任务级状态管理的完整结构，包括核心状态、事件处理方法和用户主动操作。
 * 为什么这样做：Zustand Store 需要明确的类型定义以保证类型安全。
 */
interface TaskStateStoreState {
  // === 核心数据 ===
  /** 当前任务 ID */
  taskId: string | null;
  /** 当前任务状态 */
  taskStatus: TaskStatus | null;
  /** 当前 Plan ID */
  planId: string | null;

  /** 暂停信息 */
  pausedInfo: {
    reason: string;
    pausedAtMs: number;
    isEmotionFreeze: boolean;
  } | null;
  /** 取消信息 */
  cancelInfo: {
    reason: string;
    cancelledAtMs: number;
  } | null;

  /** 恢复信息 */
  recoveryInfo: {
    snapshotVersion: number;
    recoveredAtMs: number;
  } | null;

  // === 崩溃恢复相关 ===
  /** 系统重启后发现的未完成任务列表 */
  unfinishedTasks: UnfinishedTask[];
  /** 是否展示恢复确认弹窗 */
  isRecoveryDialogOpen: boolean;

  // === SSE 事件处理方法 ===
  /** 处理任务暂停事件 */
  onTaskPaused: (payload: TaskPausedPayload) => void;
  /** 处理任务恢复事件 */
  onTaskResumed: (payload: TaskResumedPayload) => void;
  /** 处理任务超时事件 */
  onTaskTimeout: (payload: TaskTimeoutPayload) => void;
  /** 处理恢复启动事件 */
  onRecoveryStarted: (payload: TaskRecoveryStartedPayload) => void;
  /** 处理恢复完成事件 */
  onRecoveryCompleted: (payload: TaskRecoveryCompletedPayload) => void;
  /** 处理恢复失败事件 */
  onRecoveryFailed: (payload: TaskRecoveryFailedPayload) => void;

  // === 用户主动操作 ===
  /** 发送取消任务命令 */
  sendCancelTask: (reason?: string) => Promise<void>;
  /** 发送暂停任务命令 */
  sendPauseTask: () => Promise<void>;
  /** 发送恢复任务命令 */
  sendResumeTask: () => Promise<void>;

  // === 操作方法 ===
  /** 设置任务 ID 和状态 */
  setTaskState: (taskId: string, taskStatus: TaskStatus, planId?: string) => void;
  /** 清除任务状态 */
  clearTaskState: () => void;
  /** 设置未完成任务列表 */
  setUnfinishedTasks: (tasks: UnfinishedTask[]) => void;
  /** 设置恢复弹窗显示状态 */
  setRecoveryDialogOpen: (open: boolean) => void;

  // === 按钮启用条件判断 ===
  /** 检查任务是否可取消 */
  isCancellable: () => boolean;
  /** 检查任务是否可暂停 */
  isPausable: () => boolean;
  /** 检查任务是否可恢复 */
  isResumable: () => boolean;
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 通过 HTTP POST 向后端发送 WebSocket 命令。
 * 做什么：将命令序列化为 JSON 发送到后端 WebSocket 命令端点。
 * 为什么这样做：Electron 前端通过 HTTP 代理转发 WebSocket 命令给 Python 后端。
 * 输入输出：type 为命令类型字符串，payload 为命令载荷。
 * 边界条件：后端不可达时会抛出异常，调用方需处理。
 * 异常行为：网络异常时向上抛出，由 UI 层展示错误提示。
 */
async function sendWebSocketCommand(
  type: string,
  payload: Record<string, unknown>
): Promise<void> {
  const url = `${AI_SERVICE_BASE_URL}/api/ws/command`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, payload }),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => '未知错误');
    throw new Error(`发送 ${type} 命令失败: HTTP ${response.status} - ${errorText}`);
  }
}

// ============================================================
// Store 实现
// ============================================================

/**
 * 任务状态管理 Store。
 * 做什么：维护任务级生命周期状态，提供 SSE 事件处理和用户操作方法。
 * 为什么这样做：Phase 10 引入的任务级状态（暂停/恢复/超时）需要独立管理，
 *               避免污染 dagWorkflowStore 的 DAG 展示级状态。
 */
export const useTaskStateStore = create<TaskStateStoreState>((set, get) => ({
  // === 初始状态 ===
  taskId: null,
  taskStatus: null,
  planId: null,
  pausedInfo: null,
  cancelInfo: null,
  recoveryInfo: null,
  unfinishedTasks: [],
  isRecoveryDialogOpen: false,

  // ============================================================
  // SSE 事件处理方法
  // ============================================================

  /**
   * 处理任务暂停事件。
   * 做什么：将任务状态标记为 PAUSED，保存暂停信息。
   * 为什么这样做：后端推送 EVT_TASK_PAUSED 后，前端需冻结 DAG 渲染并展示暂停态 UI。
   * 输入输出：payload 包含 task_id、reason、is_emotion_freeze、paused_at_ms。
   */
  onTaskPaused: (payload: TaskPausedPayload): void => {
    set({
      taskStatus: 'PAUSED',
      pausedInfo: {
        reason: payload.reason,
        pausedAtMs: payload.paused_at_ms,
        isEmotionFreeze: payload.is_emotion_freeze || false,
      },
    });
  },

  /**
   * 处理任务恢复事件。
   * 做什么：将任务状态标记为 RUNNING，清除暂停信息。
   * 为什么这样做：后端推送 EVT_TASK_RESUMED 后，前端需恢复 DAG 渲染为正常运行态。
   * 输入输出：payload 包含 task_id 和 dag_state_snapshot。
   */
  onTaskResumed: (payload: TaskResumedPayload): void => {
    set({
      taskStatus: 'RUNNING',
      pausedInfo: null,
      recoveryInfo: null,
    });
  },

  /**
   * 处理任务超时事件。
   * 做什么：将任务状态标记为 TIMED_OUT。
   * 为什么这样做：后端推送 EVT_TASK_TIMEOUT 后，前端需展示超时提示并允许用户选择恢复或取消。
   * 输入输出：payload 包含 task_id、timeout_seconds、terminated_states。
   */
  onTaskTimeout: (payload: TaskTimeoutPayload): void => {
    set({
      taskStatus: 'TIMED_OUT',
    });
  },

  /**
   * 处理恢复启动事件。
   * 做什么：将任务状态标记为 RECOVERING。
   * 为什么这样做：系统重启后检测到未完成任务，前端展示恢复进度。
   * 输入输出：payload 包含 task_id 和 snapshot_version。
   */
  onRecoveryStarted: (payload: TaskRecoveryStartedPayload): void => {
    set({
      taskStatus: 'RECOVERING',
      recoveryInfo: {
        snapshotVersion: payload.snapshot_version,
        recoveredAtMs: Date.now(),
      },
    });
  },

  /**
   * 处理恢复完成事件。
   * 做什么：将任务状态标记为 RUNNING，保存恢复信息。
   * 为什么这样做：恢复成功后任务从断点继续执行，前端需更新恢复标记。
   * 输入输出：payload 包含 task_id、recovered_cursor、recovered_states。
   */
  onRecoveryCompleted: (payload: TaskRecoveryCompletedPayload): void => {
    const currentRecoveryInfo = get().recoveryInfo;
    set({
      taskStatus: 'RUNNING',
      recoveryInfo: {
        snapshotVersion: currentRecoveryInfo?.snapshotVersion || 0,
        recoveredAtMs: Date.now(),
      },
    });
  },

  /**
   * 处理恢复失败事件。
   * 做什么：将任务状态标记为 TERMINATED。
   * 为什么这样做：恢复失败时任务不可恢复，前端展示错误并禁用操作按钮。
   * 输入输出：payload 包含 task_id 和 reason。
   */
  onRecoveryFailed: (payload: TaskRecoveryFailedPayload): void => {
    set({
      taskStatus: 'TERMINATED',
      recoveryInfo: null,
    });
  },

  // ============================================================
  // 用户主动操作
  // ============================================================

  /**
   * 发送取消任务命令。
   * 做什么：通过 WebSocket 向后端发送 CMD_CANCEL_TASK 命令。
   * 为什么这样做：用户确认取消后，后端需标记 Plan 为 TERMINATED 并保存终止快照。
   * 输入输出：reason 为可选的取消原因，可为空。
   * 边界条件：taskId 为空时不做任何操作。
   * 异常行为：后端不可达时抛出异常，由 UI 层展示错误提示。
   */
  sendCancelTask: async (reason?: string): Promise<void> => {
    const { taskId } = get();
    if (!taskId) return;

    await sendWebSocketCommand('CMD_CANCEL_TASK', {
      task_id: taskId,
      reason: reason || undefined,
    });
  },

  /**
   * 发送暂停任务命令。
   * 做什么：通过 WebSocket 向后端发送 CMD_PAUSE_TASK 命令。
   * 为什么这样做：用户点击暂停后，后端需保存当前 DagEngineState 快照并标记为 PAUSED。
   * 输入输出：无额外参数。
   * 边界条件：taskId 为空时不做任何操作。
   * 异常行为：后端不可达时抛出异常，由 UI 层展示错误提示。
   */
  sendPauseTask: async (): Promise<void> => {
    const { taskId } = get();
    if (!taskId) return;

    await sendWebSocketCommand('CMD_PAUSE_TASK', {
      task_id: taskId,
    });
  },

  /**
   * 发送恢复任务命令。
   * 做什么：通过 WebSocket 向后端发送 CMD_RESUME_TASK 命令。
   * 为什么这样做：用户点击恢复后，后端需从快照恢复 DagEngineState 并继续执行。
   * 输入输出：无额外参数。
   * 边界条件：taskId 为空时不做任何操作。
   * 异常行为：后端不可达时抛出异常，由 UI 层展示错误提示。
   */
  sendResumeTask: async (): Promise<void> => {
    const { taskId } = get();
    if (!taskId) return;

    const recoverySnapshotVersion = get().recoveryInfo?.snapshotVersion;
    await sendWebSocketCommand('CMD_RESUME_TASK', {
      task_id: taskId,
      snapshot_version: recoverySnapshotVersion,
    });
  },

  // ============================================================
  // 操作方法
  // ============================================================

  /**
   * 设置任务 ID 和状态。
   * 做什么：在 DAG Plan 创建时设置任务级上下文。
   * 为什么这样做：SSEManager 在收到 EVT_DAG_PLAN_CREATED 时需要同时初始化任务状态。
   */
  setTaskState: (taskId: string, taskStatus: TaskStatus, planId?: string): void => {
    set({
      taskId,
      taskStatus,
      planId: planId || null,
      pausedInfo: null,
      cancelInfo: null,
      recoveryInfo: null,
    });
  },

  /**
   * 清除任务状态。
   * 做什么：重置所有任务状态为初始值。
   * 为什么这样做：任务完成或取消后需要清理状态，防止残留数据影响下次任务。
   */
  clearTaskState: (): void => {
    set({
      taskId: null,
      taskStatus: null,
      planId: null,
      pausedInfo: null,
      cancelInfo: null,
      recoveryInfo: null,
      unfinishedTasks: [],
      isRecoveryDialogOpen: false,
    });
  },

  /**
   * 设置未完成任务列表。
   * 做什么：系统重启后检测到未完成任务时设置列表并打开恢复弹窗。
   */
  setUnfinishedTasks: (tasks: UnfinishedTask[]): void => {
    set({
      unfinishedTasks: tasks,
      isRecoveryDialogOpen: tasks.length > 0,
    });
  },

  /**
   * 设置恢复弹窗显示状态。
   * 做什么：控制恢复确认弹窗的显示与隐藏。
   */
  setRecoveryDialogOpen: (open: boolean): void => {
    set({ isRecoveryDialogOpen: open });
  },

  // ============================================================
  // 按钮启用条件判断
  // ============================================================

  /**
   * 检查任务是否可取消。
   * 做什么：根据当前任务状态判断取消按钮是否应启用。
   * 为什么这样做：防止在不合法状态下发取消命令。
   * 输入输出：无。
   * 边界条件：无活跃任务时返回 false。
   */
  isCancellable: (): boolean => {
    const { taskStatus } = get();
    return (
      taskStatus === 'RUNNING' ||
      taskStatus === 'PAUSED' ||
      taskStatus === 'GATING_SUSPENDED' ||
      taskStatus === 'TIMED_OUT'
    );
  },

  /**
   * 检查任务是否可暂停。
   * 做什么：根据当前任务状态判断暂停按钮是否应启用。
   * 为什么这样做：防止在不合法状态下发暂停命令。
   * 输入输出：无。
   * 边界条件：无活跃任务时返回 false。
   */
  isPausable: (): boolean => {
    const { taskStatus } = get();
    return taskStatus === 'RUNNING' || taskStatus === 'GATING_SUSPENDED';
  },

  /**
   * 检查任务是否可恢复。
   * 做什么：根据当前任务状态判断恢复按钮是否应启用。
   * 为什么这样做：防止在不合法状态下发恢复命令。
   * 输入输出：无。
   * 边界条件：无活跃任务时返回 false。
   */
  isResumable: (): boolean => {
    const { taskStatus } = get();
    return (
      taskStatus === 'PAUSED' ||
      taskStatus === 'TIMED_OUT' ||
      taskStatus === 'RECOVERING'
    );
  },
}));
