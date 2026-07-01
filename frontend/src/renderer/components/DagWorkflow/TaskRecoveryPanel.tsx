/**
 * TaskRecoveryPanel — Phase 10 任务恢复管理面板。
 * 做什么：系统崩溃重启后，检测到未完成任务时展示恢复确认对话框，
 *         允许用户选择「恢复任务」或「取消任务」。
 * 为什么这样做：崩溃恢复需要用户显式确认，避免自动恢复导致副作用。
 * 输入输出：数据来源为 taskStateStore，包含未完成任务列表。
 * 边界条件：无未完成任务时不渲染。
 * 异常行为：发送命令失败时通过 createErrorToast 展示错误提示。
 */
import React, { useState, useCallback } from 'react';
import { useTaskStateStore } from '../../stores/taskStateStore';
import { createErrorToast } from '../../stores/errorToastStore';
import { DagIconRefresh, DagIconStopCircle, DagIconPlayCircle } from './DagIcons';
import type { UnfinishedTask } from '../../../shared/types';
import './TaskRecoveryPanel.css';

/**
 * 格式化时间戳为可读字符串。
 */
function formatTimestamp(ms: number): string {
  const date = new Date(ms);
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * 获取触发事件的中文描述。
 */
function getTriggerEventLabel(event: string): string {
  const map: Record<string, string> = {
    system_crash: '系统异常终止',
    user_terminate: '用户主动终止',
    power_loss: '系统断电',
    unknown: '未知原因',
  };
  return map[event] || event || '未知原因';
}

/**
 * TaskRecoveryPanel 组件属性。
 */
interface TaskRecoveryPanelProps {
  /** 未完成任务列表 */
  unfinishedTasks: UnfinishedTask[];
  /** 恢复任务回调 */
  onRecover: (taskId: string, snapshotVersion?: number) => void;
  /** 放弃任务回调 */
  onDiscard: (taskId: string) => void;
}

/**
 * 任务恢复管理面板组件。
 */
export const TaskRecoveryPanel: React.FC<TaskRecoveryPanelProps> = ({
  unfinishedTasks,
  onRecover,
  onDiscard,
}) => {
  const [isSending, setIsSending] = useState<string | null>(null);

  // 空列表不渲染
  if (!unfinishedTasks || unfinishedTasks.length === 0) return null;

  return (
    <div className="task-recovery-overlay">
      <div className="task-recovery-dialog">
        <div className="task-recovery-header">
          <DagIconRefresh width="24" height="24" style={{ color: '#7c4dff' }} />
          <span className="task-recovery-title">发现未完成的任务</span>
        </div>

        <div className="task-recovery-body">
          {unfinishedTasks.map((task) => (
            <div key={task.taskId} className="task-recovery-card">
              {/* 任务进度信息 */}
              <div className="task-recovery-progress">
                <div className="task-recovery-progress-bar">
                  <div
                    className="task-recovery-progress-fill"
                    style={{
                      width: `${task.totalStates > 0
                        ? Math.round((task.cursor / task.totalStates) * 100)
                        : 0}%`
                    }}
                  />
                </div>
                <span className="task-recovery-progress-text">
                  {task.cursor}/{task.totalStates}
                </span>
              </div>

              {/* 任务详情 */}
              <div className="task-recovery-details">
                <div className="task-recovery-detail-row">
                  <span className="task-recovery-detail-label">任务 ID</span>
                  <span className="task-recovery-detail-value task-recovery-mono">
                    {task.taskId.slice(-12)}
                  </span>
                </div>
                <div className="task-recovery-detail-row">
                  <span className="task-recovery-detail-label">保存时间</span>
                  <span className="task-recovery-detail-value">
                    {formatTimestamp(task.savedAtMs)}
                  </span>
                </div>
                <div className="task-recovery-detail-row">
                  <span className="task-recovery-detail-label">触发事件</span>
                  <span className="task-recovery-detail-value">
                    {getTriggerEventLabel(task.triggerEvent)}
                  </span>
                </div>
                {task.snapshotVersion > 0 && (
                  <div className="task-recovery-detail-row">
                    <span className="task-recovery-detail-label">快照版本</span>
                    <span className="task-recovery-detail-value task-recovery-mono">
                      v{task.snapshotVersion}
                    </span>
                  </div>
                )}
              </div>

              {/* 操作按钮 */}
              <div className="task-recovery-actions">
                <button
                  className="task-recovery-btn recover"
                  onClick={() => {
                    setIsSending(task.taskId);
                    onRecover(task.taskId, task.snapshotVersion);
                  }}
                  disabled={isSending === task.taskId}
                  type="button"
                >
                  {isSending === task.taskId ? (
                    '处理中...'
                  ) : (
                    <>
                      <DagIconPlayCircle width="14" height="14" />
                      恢复任务
                    </>
                  )}
                </button>
                <button
                  className="task-recovery-btn discard"
                  onClick={() => {
                    setIsSending(task.taskId);
                    onDiscard(task.taskId);
                  }}
                  disabled={isSending === task.taskId}
                  type="button"
                >
                  <DagIconStopCircle width="14" height="14" />
                  取消任务
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * 挂载在系统层面的 TaskRecoveryContainer — 自动从 taskStateStore 读取未完成任务并渲染。
 * 做什么：当 taskStateStore 中检测到未完成任务时自动展示恢复弹窗。
 * 为什么这样做：避免在每个页面组件中手动挂载 TaskRecoveryPanel。
 */
export const TaskRecoveryContainer: React.FC = () => {
  const unfinishedTasks = useTaskStateStore((s) => s.unfinishedTasks);
  const sendResumeTask = useTaskStateStore((s) => s.sendResumeTask);
  const sendCancelTask = useTaskStateStore((s) => s.sendCancelTask);
  const setRecoveryDialogOpen = useTaskStateStore((s) => s.setRecoveryDialogOpen);
  const clearTaskState = useTaskStateStore((s) => s.clearTaskState);
  const [handlingTaskId, setHandlingTaskId] = useState<string | null>(null);

  const handleRecover = useCallback(async (taskId: string) => {
    setHandlingTaskId(taskId);
    try {
      await sendResumeTask();
      setRecoveryDialogOpen(false);
    } catch (err) {
      createErrorToast(
        'ERROR',
        'task_recovery',
        `恢复任务失败: ${err instanceof Error ? err.message : '未知错误'}`,
      );
    } finally {
      setHandlingTaskId(null);
    }
  }, [sendResumeTask, setRecoveryDialogOpen]);

  const handleDiscard = useCallback(async (taskId: string) => {
    setHandlingTaskId(taskId);
    try {
      await sendCancelTask('用户放弃恢复');
      clearTaskState();
    } catch (err) {
      createErrorToast(
        'ERROR',
        'task_recovery',
        `取消任务失败: ${err instanceof Error ? err.message : '未知错误'}`,
      );
    } finally {
      setHandlingTaskId(null);
    }
  }, [sendCancelTask, clearTaskState]);

  if (!unfinishedTasks || unfinishedTasks.length === 0) return null;

  return (
    <TaskRecoveryPanel
      unfinishedTasks={unfinishedTasks}
      onRecover={handleRecover}
      onDiscard={handleDiscard}
    />
  );
};
