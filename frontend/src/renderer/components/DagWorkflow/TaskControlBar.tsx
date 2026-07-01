/**
 * TaskControlBar — Phase 10 任务控制栏组件。
 * 做什么：提供「取消任务」「暂停任务」「恢复任务」三个操作按钮，
 *         以及取消确认弹窗和暂停态提示横幅。
 * 为什么这样做：用户需要在 DAG 工作流执行过程中主动控制任务生命周期，
 *               取消操作需要二次确认以防误触，暂停操作一键直接执行。
 * 输入输出：数据来源为 taskStateStore，按钮状态由 isCancellable/isPausable/isResumable 决定。
 * 边界条件：taskStatus 为 null 时不渲染控制栏。
 * 异常行为：发送命令失败时通过 createErrorToast 展示错误提示。
 */
import React, { useState, useCallback } from 'react';
import { useTaskStateStore, TASK_STATUS_LABEL, type TaskStatus } from '../../stores/taskStateStore';
import { createErrorToast } from '../../stores/errorToastStore';
import {
  DagIconStopCircle,
  DagIconPauseCircle,
  DagIconPlayCircle,
  DagIconRefresh,
  DagIconAlertOctagon,
} from './DagIcons';
import './TaskControlBar.css';

/**
 * 获取任务状态对应的 CSS 类名。
 * 做什么：将 TaskStatus 映射为 dot 的 CSS 类名。
 * 为什么这样做：不同状态需要不同颜色的指示灯。
 */
function getStatusDotClass(taskStatus: TaskStatus | null): string {
  switch (taskStatus) {
    case 'RUNNING':
      return 'running';
    case 'PAUSED':
      return 'paused';
    case 'RECOVERING':
      return 'recovering';
    case 'TIMED_OUT':
      return 'timed-out';
    case 'TERMINATED':
    case 'FAILED':
      return 'terminated';
    case 'SUCCEEDED':
      return 'succeeded';
    default:
      return 'default';
  }
}

/**
 * 格式化暂停时长。
 * 做什么：将毫秒时间戳转换为 HH:MM:SS 格式。
 */
function formatPausedTime(pausedAtMs: number): string {
  const date = new Date(pausedAtMs);
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/**
 * TaskControlBar 组件。
 */
export const TaskControlBar: React.FC = () => {
  const taskId = useTaskStateStore((s) => s.taskId);
  const taskStatus = useTaskStateStore((s) => s.taskStatus);
  const pausedInfo = useTaskStateStore((s) => s.pausedInfo);
  const recoveryInfo = useTaskStateStore((s) => s.recoveryInfo);
  const isCancellable = useTaskStateStore((s) => s.isCancellable);
  const isPausable = useTaskStateStore((s) => s.isPausable);
  const isResumable = useTaskStateStore((s) => s.isResumable);
  const sendCancelTask = useTaskStateStore((s) => s.sendCancelTask);
  const sendPauseTask = useTaskStateStore((s) => s.sendPauseTask);
  const sendResumeTask = useTaskStateStore((s) => s.sendResumeTask);

  /** 取消确认弹窗是否打开 */
  const [isCancelDialogOpen, setIsCancelDialogOpen] = useState(false);
  /** 取消原因输入 */
  const [cancelReason, setCancelReason] = useState('');
  /** 正在发送命令（防重复点击） */
  const [isSending, setIsSending] = useState(false);

  /**
   * 打开取消确认弹窗。
   * 做什么：弹出二次确认弹窗，让用户填写取消原因。
   */
  const openCancelDialog = useCallback(() => {
    setCancelReason('');
    setIsCancelDialogOpen(true);
  }, []);

  /**
   * 关闭取消确认弹窗。
   */
  const closeCancelDialog = useCallback(() => {
    setIsCancelDialogOpen(false);
    setCancelReason('');
  }, []);

  /**
   * 确认取消任务。
   * 做什么：发送 CMD_CANCEL_TASK 命令并关闭弹窗。
   * 为什么这样做：用户二次确认后才真正发送取消命令，防止误触。
   */
  const confirmCancel = useCallback(async () => {
    if (isSending) return;
    setIsSending(true);
    try {
      await sendCancelTask(cancelReason || undefined);
      closeCancelDialog();
    } catch (err) {
      createErrorToast(
        'ERROR',
        'task_control',
        `取消任务失败: ${err instanceof Error ? err.message : '未知错误'}`,
      );
    } finally {
      setIsSending(false);
    }
  }, [cancelReason, isSending, sendCancelTask, closeCancelDialog]);

  /**
   * 暂停任务。
   * 做什么：发送 CMD_PAUSE_TASK 命令。
   * 为什么这样做：暂停操作无需二次确认，一键直接执行。
   */
  const handlePause = useCallback(async () => {
    if (isSending) return;
    setIsSending(true);
    try {
      await sendPauseTask();
    } catch (err) {
      createErrorToast(
        'ERROR',
        'task_control',
        `暂停任务失败: ${err instanceof Error ? err.message : '未知错误'}`,
      );
    } finally {
      setIsSending(false);
    }
  }, [isSending, sendPauseTask]);

  /**
   * 恢复任务。
   * 做什么：发送 CMD_RESUME_TASK 命令。
   * 为什么这样做：恢复操作无需二次确认，一键直接执行。
   */
  const handleResume = useCallback(async () => {
    if (isSending) return;
    setIsSending(true);
    try {
      await sendResumeTask();
    } catch (err) {
      createErrorToast(
        'ERROR',
        'task_control',
        `恢复任务失败: ${err instanceof Error ? err.message : '未知错误'}`,
      );
    } finally {
      setIsSending(false);
    }
  }, [isSending, sendResumeTask]);

  // 无活跃任务时不渲染
  if (!taskStatus) return null;

  const statusLabel = TASK_STATUS_LABEL[taskStatus] || taskStatus;
  const dotClass = getStatusDotClass(taskStatus);

  return (
    <>
      <div className="task-control-bar">
        {/* 状态指示器 */}
        <div className="task-control-status">
          <span className={`task-control-status-dot ${dotClass}`} />
          <span className="task-control-status-text">{statusLabel}</span>
          {recoveryInfo && (
            <span style={{ fontSize: '11px', color: '#7c4dff', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <DagIconRefresh width="11" height="11" />
              从断点恢复
            </span>
          )}
        </div>

        {/* 暂停时显示暂停态提示 */}
        {taskStatus === 'PAUSED' && pausedInfo && (
          <span className="task-paused-banner-time" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <DagIconPauseCircle width="12" height="12" />
            {formatPausedTime(pausedInfo.pausedAtMs)} 暂停
            {pausedInfo.isEmotionFreeze && ' · 情感安抚中'}
          </span>
        )}

        {/* 🛑 取消任务按钮 */}
        <button
          className="task-control-btn danger"
          onClick={openCancelDialog}
          disabled={!isCancellable() || isSending}
          aria-label="取消任务"
          title="取消当前任务（不可恢复）"
          type="button"
        >
          <DagIconStopCircle width="14" height="14" />
          取消
        </button>

        {/* ⏸ 暂停任务按钮 */}
        <button
          className="task-control-btn pause"
          onClick={handlePause}
          disabled={!isPausable() || isSending}
          aria-label="暂停任务"
          title="暂停当前任务（可恢复）"
          type="button"
        >
          <DagIconPauseCircle width="14" height="14" />
          暂停
        </button>

        {/* ▶ 恢复任务按钮 */}
        <button
          className="task-control-btn resume"
          onClick={handleResume}
          disabled={!isResumable() || isSending}
          aria-label="恢复任务"
          title="从暂停/超时/崩溃恢复继续执行"
          type="button"
        >
          <DagIconPlayCircle width="14" height="14" />
          恢复
        </button>
      </div>

      {/* 取消确认弹窗 */}
      {isCancelDialogOpen && (
        <div className="task-cancel-overlay" onClick={closeCancelDialog}>
          <div
            className="task-cancel-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="task-cancel-dialog-title">
              <DagIconAlertOctagon width="18" height="18" />
              确认取消任务
            </div>

            <div className="task-cancel-dialog-body">
              当前任务正在执行中，取消后将标记为已终止。
            </div>

            <div className="task-cancel-warning">
              <DagIconAlertOctagon width="12" height="12" style={{ marginRight: 4, verticalAlign: 'middle' }} />
              取消后无法恢复，已完成的进度将被丢弃
            </div>

            <input
              className="task-cancel-reason-input"
              type="text"
              placeholder="取消原因（可选）"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') confirmCancel();
              }}
              autoFocus
            />

            <div className="task-cancel-dialog-actions">
              <button
                className="task-control-btn"
                onClick={closeCancelDialog}
                disabled={isSending}
                type="button"
              >
                撤销
              </button>
              <button
                className="task-control-btn danger"
                onClick={confirmCancel}
                disabled={isSending}
                type="button"
              >
                <DagIconStopCircle width="14" height="14" />
                {isSending ? '处理中...' : '确认取消'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
