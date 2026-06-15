/**
 * PanelTransition —— 统一面板加载过渡组件
 *
 * 职责：
 * - 面板打开时：显示骨架屏（加载态）→ 550ms 后内容淡入（内容态）
 * - 面板关闭时：触发 300ms 关闭动画，结束后通知父组件
 * - 严格只使用 transform 和 opacity 进行动画（GPU Composited）
 * - 完全匹配深色主题 + 赛博朋克色彩体系
 */
import React, { useState, useEffect, useCallback } from 'react';
import './PanelTransition.css';

interface PanelTransitionProps {
  children: React.ReactNode;
  isLoading?: boolean;
  className?: string;
  /** 是否触发关闭退出动画（由外部控制） */
  exiting?: boolean;
  /** 关闭动画完成回调 */
  onExited?: () => void;
}

/**
 * 面板加载过渡动画组件
 * - 三种状态：loading（骨架屏）→ entering（内容淡入）→ entered（稳定展示）
 * - 关闭时：exiting（内容淡出）→ onExited 回调
 * - 所有状态切换严格使用 transform + opacity，零重排
 */
export const PanelTransition: React.FC<PanelTransitionProps> = ({
  children,
  isLoading = false,
  className = '',
  exiting = false,
  onExited,
}) => {
  /**
   * 内部动画状态机
   * 'loading'   - 展示骨架屏，等待数据就绪
   * 'entering'  - 数据已就绪，执行淡入动画
   * 'entered'   - 动画完成，稳定展示内容
   * 'exiting'   - 开始退出动画
   * 'exited'    - 退出动画完成
   */
  const [phase, setPhase] = useState<'loading' | 'entering' | 'entered' | 'exiting' | 'exited'>(
    isLoading ? 'loading' : 'entered'
  );

  // ========== 加载 → 进入 ==========
  useEffect(() => {
    if (!isLoading && phase === 'loading') {
      // 数据就绪，等待一帧后开始进入动画
      const frame = requestAnimationFrame(() => {
        setPhase('entering');
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [isLoading, phase]);

  // entering → entered：动画结束时切换
  useEffect(() => {
    if (phase === 'entering') {
      const timer = setTimeout(() => setPhase('entered'), 450);
      return () => clearTimeout(timer);
    }
  }, [phase]);

  // ========== 退出 ==========
  useEffect(() => {
    if (exiting && (phase === 'entered' || phase === 'entering')) {
      setPhase('exiting');
    }
  }, [exiting, phase]);

  // exiting → exited：动画结束时回调
  useEffect(() => {
    if (phase === 'exiting') {
      const timer = setTimeout(() => {
        setPhase('exited');
        onExited?.();
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [phase, onExited]);

  // 外部切换 isLoading 时重置
  useEffect(() => {
    if (isLoading && phase !== 'loading') {
      setPhase('loading');
    }
  }, [isLoading, phase]);

  // ========== 渲染 ==========

  /** 骨架屏：纯 CSS 动画，无 JS 开销 */
  const renderSkeleton = () => (
    <div className="panel-skeleton" aria-label="加载中…">
      <div className="skeleton-shimmer">
        <div className="skeleton-row skeleton-row-title" />
        <div className="skeleton-row skeleton-row-subtitle" />
        <div className="skeleton-row skeleton-row-block" />
        <div className="skeleton-row skeleton-row-block short" />
        <div className="skeleton-row skeleton-row-block" />
        <div className="skeleton-loader-bar">
          <div className="loader-dot" />
          <span className="loader-text">LOADING</span>
          <div className="loader-dot" />
        </div>
      </div>
    </div>
  );

  /** 内容区域 */
  const renderContent = () => (
    <div
      className={`panel-content ${phase === 'entering' ? 'content-entering' : ''} ${phase === 'exiting' ? 'content-exiting' : ''}`}
    >
      {children}
    </div>
  );

  // 已完全退出 → 不渲染任何内容
  if (phase === 'exited') {
    return null;
  }

  return (
    <div className={`panel-transition-root ${className}`}>
      {/* 加载态展示骨架屏 */}
      {(phase === 'loading') && renderSkeleton()}

      {/* 进入中 / 已进入 / 退出中 → 展示内容（含动画 class） */}
      {(phase === 'entering' || phase === 'entered' || phase === 'exiting') && renderContent()}
    </div>
  );
};
