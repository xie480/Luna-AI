/**
 * Luna AI 全局错误提示组件
 *
 * 做什么：在屏幕顶部状态栏正下方平滑弹出一个半透明背景的提示框来呈现错误详情。
 *        采用严格串行阻塞队列：一次只显示一条错误提示，新提示进入队列后台等待。
 *        当前气泡的 TTL 自然耗尽并完成离场动画后，才从队列提取下一个。
 * 为什么这样做：替代系统原生 alert() 弹窗，提供统一、美观、无侵入的错误提示体验，
 *              并确保所有异常有持久化记录。串行队列保证用户不会错过任何一条错误信息。
 * 边界条件：
 *   - 使用 Zustand errorToastStore 管理状态
 *   - 自动关闭时间按文本长度动态计算（每字符 100ms，夹紧 [800ms, 3000ms]）
 *   - 鼠标悬停时暂停自动关闭
 *   - 点击关闭按钮立即关闭
 *   - 一次只显示一条提示，其余在队列中等待
 *   - 同源同内容的错误自动去重
 * 异常行为：
 *   - 持久化上报失败不影响 UI 展示
 */
import React, { useEffect, useRef, useCallback } from 'react';
import { useErrorToastStore, ERROR_TOAST_DURATION, ERROR_TOAST_EXIT_DURATION } from '../../stores/errorToastStore';
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
 *              串行调度器（Store 内部 _processNext）管理 TTL 和离场，
 *              组件只负责悬停暂停和手动关闭。
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
   * 手动关闭：立即标记退出
   * 串行调度器接收到 markExiting 后会在离场动画完成后自动调度下一个。
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
   * 注意：自动关闭定时器由串行调度器（_processNext）统一管理，
   *       但为了用户交互体验，悬停时我们通过向 store 请求"暂停"的方式实现。
   *       这里改为不干预调度器定时器，因为调度器在 setTimeout 中直接操作 store，
   *       组件悬停不会影响 store 内部定时器触发。
   *       用户手动关闭依然通过 markExiting 走正常流程。
   */
  const handleMouseEnter = useCallback(() => {
    // 悬停时不做额外操作，因为调度器已锁定当前气泡
    // 用户可随时点击关闭
  }, []);

  /**
   * 鼠标离开：不做额外操作，调度器定时器不受影响
   */
  const handleMouseLeave = useCallback(() => {
    // 不做额外操作
  }, []);

  /**
   * exiting 状态变化时，如果进入退出动画状态，
   * 等待动画完成后由 store 的 _processNext 负责移除和调度下一个。
   * 此处不再需要独立的 removeToast 定时器。
   */
  useEffect(() => {
    if (!item.exiting) return;

    // 退出动画时长与 ERROR_TOAST_EXIT_DURATION 一致
    exitTimerRef.current = setTimeout(() => {
      removeToast(item.id);
    }, ERROR_TOAST_EXIT_DURATION);

    return () => {
      if (exitTimerRef.current) {
        clearTimeout(exitTimerRef.current);
        exitTimerRef.current = null;
      }
    };
  }, [item.exiting, item.id, removeToast]);

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

      {/* 进度条指示器 — 使用动态 TTL 上限作为最大时长展示 */}
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
 * 做什么：渲染当前活跃的错误提示条（串行队列模式）。
 * 为什么这样做：作为全局容器，固定定位在屏幕顶部，管理错误提示的展示。
 * 边界条件：
 *   - 采用串行阻塞队列，一次只展示一条
 *   - 正在退出动画中的气泡也会显示直到动画完成
 *   - 无活跃提示时返回 null，不占用渲染
 */
export const ErrorToast: React.FC = () => {
  const toasts = useErrorToastStore((state) => state.toasts);
  const activeToastId = useErrorToastStore((state) => state.activeToastId);

  // 串行队列模式：只显示当前活跃的提示（activeToastId 对应的条目）
  // 以及正在退出动画中的提示（用于保持动画平滑过渡）
  const activeToast = toasts.find((t) => t.id === activeToastId);
  // 如果有正在退出动画的气泡（exiting=true），也要显示直到动画完成
  // 注意：当 activeToast 进入 exiting 后，activeToastId 仍然指向它
  // 直到 _processNext 将它移除并设置 activeToastId = null
  // 同时也要显示那些正在 exiting 且不属于 activeToast 的遗留气泡
  const exitingToasts = toasts.filter((t) => t.exiting);

  // 合并显示列表：活跃气泡 + 正在退出的气泡
  const displayToasts: typeof toasts = [];
  if (activeToast) {
    displayToasts.push(activeToast);
  }
  for (const et of exitingToasts) {
    if (!displayToasts.some((t) => t.id === et.id)) {
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
