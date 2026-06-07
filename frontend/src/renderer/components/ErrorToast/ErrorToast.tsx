/**
 * Luna AI 全局错误提示组件
 *
 * 做什么：在屏幕顶部状态栏正下方平滑弹出一个半透明背景的提示框来呈现错误详情。
 *        同时触发数据持久化逻辑，将错误信息插入数据库进行日志记录。
 * 为什么这样做：替代系统原生 alert() 弹窗，提供统一、美观、无侵入的错误提示体验，
 *              并确保所有异常有持久化记录。
 * 边界条件：
 *   - 使用 Zustand errorToastStore 管理状态
 *   - 每个错误提示默认 6 秒后自动关闭
 *   - 鼠标悬停时暂停自动关闭
 *   - 点击关闭按钮立即关闭
 *   - 最多同时展示 3 条提示
 *   - 同源同内容的错误自动去重
 * 异常行为：
 *   - 持久化上报失败不影响 UI 展示
 */
import React, { useEffect, useRef, useCallback } from 'react';
import { useErrorToastStore, ERROR_TOAST_DURATION } from '../../stores/errorToastStore';
import { reportErrorLog } from '../../services/errorLogService';
import './ErrorToast.css';

/** 级别的图标映射 */
const LEVEL_ICONS: Record<string, string> = {
  ERROR: '✕',
  CRITICAL: '⚠',
  WARN: '!',
  INFO: 'i',
  SUCCESS: '✓',
};

/** 级别对应的 CSS 类名 */
const LEVEL_CLASSES: Record<string, string> = {
  ERROR: 'level-error',
  CRITICAL: 'level-critical',
  WARN: 'level-warn',
  INFO: 'level-info',
  SUCCESS: 'level-success',
};

/**
 * 单条错误提示子组件
 *
 * 做什么：渲染单条错误提示条，管理其自动关闭定时器和持久化上报。
 * 为什么这样做：每个提示条独立管理生命周期，方便鼠标悬停暂停。
 */
const ErrorToastItem: React.FC<{
  item: ReturnType<typeof useErrorToastStore.getState>['toasts'][0];
}> = React.memo(({ item }) => {
  const markExiting = useErrorToastStore((state) => state.markExiting);
  const removeToast = useErrorToastStore((state) => state.removeToast);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const exitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasPersisted = useRef(false);

  /**
   * 持久化上报：将错误信息写入数据库
   * 只在组件挂载时执行一次
   */
  useEffect(() => {
    if (!hasPersisted.current) {
      hasPersisted.current = true;
      // 异步上报，不阻塞 UI
      reportErrorLog({
        level: item.level,
        source: item.source,
        message: item.message,
        detail: item.detail || '',
        trace_id: item.trace_id || '',
      }).catch(() => {
        // 持久化失败静默降级
      });
    }
  }, [item.level, item.source, item.message, item.detail, item.trace_id]);

  /**
   * 启动自动关闭定时器
   * 当 exiting 为 true 时不启动新定时器
   */
  useEffect(() => {
    if (item.exiting) return;

    timerRef.current = setTimeout(() => {
      markExiting(item.id);
    }, ERROR_TOAST_DURATION);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [item.id, item.exiting, markExiting]);

  /**
   * 退出动画结束后从 DOM 移除
   */
  useEffect(() => {
    if (!item.exiting) return;

    exitTimerRef.current = setTimeout(() => {
      removeToast(item.id);
    }, 500); // 与 CSS 动画时长一致

    return () => {
      if (exitTimerRef.current) {
        clearTimeout(exitTimerRef.current);
        exitTimerRef.current = null;
      }
    };
  }, [item.exiting, item.id, removeToast]);

  /**
   * 手动关闭：立即标记退出
   */
  const handleClose = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (exitTimerRef.current) {
      clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
    markExiting(item.id);
  }, [item.id, markExiting]);

  /**
   * 鼠标悬停：暂停自动关闭定时器
   */
  const handleMouseEnter = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  /**
   * 鼠标离开：重新启动自动关闭定时器（缩短为剩余 2 秒）
   */
  const handleMouseLeave = useCallback(() => {
    if (!item.exiting) {
      timerRef.current = setTimeout(() => {
        markExiting(item.id);
      }, 2000);
    }
  }, [item.exiting, item.id, markExiting]);

  const levelClass = LEVEL_CLASSES[item.level] || LEVEL_CLASSES.ERROR;
  const icon = LEVEL_ICONS[item.level] || LEVEL_ICONS.ERROR;

  return (
    <div
      className={`error-toast-item ${levelClass}${item.exiting ? ' exiting' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClose}
      role="alert"
      aria-live="assertive"
    >
      {/* 级别图标 */}
      <span className="error-toast-icon">{icon}</span>

      {/* 内容区 */}
      <div className="error-toast-content">
        <div className="error-toast-header">
          <span className="error-toast-source">{item.source}</span>
          <span className="error-toast-level-badge">{item.level}</span>
        </div>
        <div className="error-toast-message">{item.message}</div>
        {item.detail && (
          <div className="error-toast-detail">{item.detail}</div>
        )}
      </div>

      {/* 关闭按钮 */}
      <button
        className="error-toast-close"
        onClick={(e) => {
          e.stopPropagation();
          handleClose();
        }}
        aria-label="关闭错误提示"
      >
        ✕
      </button>

      {/* 进度条指示器 */}
      <div
        className={`error-toast-progress ${levelClass}`}
        style={{ '--toast-duration': `${ERROR_TOAST_DURATION}ms` } as React.CSSProperties}
      />
    </div>
  );
});

ErrorToastItem.displayName = 'ErrorToastItem';

/**
 * ErrorToast 主组件
 *
 * 做什么：渲染所有当前可见的错误提示条。
 * 为什么这样做：作为全局容器，固定定位在屏幕顶部，管理所有提示条的展示与堆叠。
 * 边界条件：
 *   - 最多同时展示 maxVisible 条
 *   - 超出部分在队列中等待前面的关闭后再展示
 */
export const ErrorToast: React.FC = () => {
  const toasts = useErrorToastStore((state) => state.toasts);
  const maxVisible = useErrorToastStore((state) => state.maxVisible);

  // 取最近 maxVisible 条非 exiting 的提示 + 正在 exiting 的提示（为了动画过渡）
  const visibleToasts = toasts.filter((t) => !t.exiting).slice(-maxVisible);
  const exitingToasts = toasts.filter((t) => t.exiting);

  // 合并：确保退出动画中的提示仍然显示直到动画完成
  const displayToasts = [...visibleToasts];
  for (const et of exitingToasts) {
    if (!displayToasts.find((t) => t.id === et.id)) {
      displayToasts.push(et);
    }
  }

  if (displayToasts.length === 0) {
    return null;
  }

  return (
    <div className="error-toast-container">
      {displayToasts.map((item) => (
        <ErrorToastItem key={item.id} item={item} />
      ))}
    </div>
  );
};
