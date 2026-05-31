import React, { useState, useRef, useCallback, useEffect } from 'react';
import TraceViewer from './TraceViewer';
import AuditLogViewer from './AuditLogViewer';
import MetricsChart from './MetricsChart';
import { useSystemStore } from '../../../stores/systemStore';
import './DebugPanel.css';

type TabType = 'trace' | 'audit' | 'metrics' | 'errors';

/** 最小窗口尺寸 */
const MIN_WIDTH = 400;
const MIN_HEIGHT = 300;

/** 缩放方向 */
type ResizeDirection = 'n' | 's' | 'w' | 'e' | 'nw' | 'ne' | 'sw' | 'se';

/**
 * DebugPanelInner: 诊断面板实际内容组件
 * 与 DebugPanel 分离，确保 hooks 在条件渲染后仍能按固定顺序调用。
 * 当 isDiagnosticOpen 为 false 时不渲染任何内容。
 */
const DebugPanelInner: React.FC<{ isOpen: boolean }> = ({ isOpen }) => {
  // 所有 hooks 必须在此无条件声明，且早于任何 if return
  const [activeTab, setActiveTab] = useState<TabType>('trace');
  const panelRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const [panelPosition, setPanelPosition] = useState<{ x: number; y: number } | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const resizeDirection = useRef<ResizeDirection | null>(null);
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0, left: 0, top: 0 });
  const [panelSize, setPanelSize] = useState<{ w: number; h: number }>({ w: 800, h: 600 });

  // 打开后重置位置和尺寸
  useEffect(() => {
    if (isOpen) {
      setPanelPosition(null);
      setPanelSize({ w: 800, h: 600 });
    }
  }, [isOpen]);

  // ===========================
  //  拖拽逻辑
  // ===========================
  const handleHeaderMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('.debug-panel-close')) return;
    if (target.closest('.debug-resize-handle')) return;

    setIsDragging(true);
    const rect = panelRef.current?.getBoundingClientRect();
    if (rect) {
      dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }
    e.preventDefault();
  }, []);

  // ===========================
  //  缩放逻辑
  // ===========================
  const handleResizeStart = useCallback(
    (dir: ResizeDirection) => (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      setIsResizing(true);
      resizeDirection.current = dir;
      const rect = panelRef.current!.getBoundingClientRect();
      resizeStart.current = {
        x: e.clientX,
        y: e.clientY,
        w: rect.width,
        h: rect.height,
        left: rect.left,
        top: rect.top,
      };
    },
    []
  );

  // 统一处理拖拽和缩放中的 mouse-move 与 mouse-up
  useEffect(() => {
    const cleanup = () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!panelRef.current) return;

      const dragging = isDraggingRef.current;
      const resizing = isResizingRef.current;

      if (dragging) {
        const newX = e.clientX - dragOffset.current.x;
        const newY = e.clientY - dragOffset.current.y;
        setPanelPosition({ x: newX, y: newY });
      }

      if (resizing && resizeDirection.current) {
        const dir = resizeDirection.current;
        const rs = resizeStart.current;
        const dx = e.clientX - rs.x;
        const dy = e.clientY - rs.y;
        let newW = rs.w;
        let newH = rs.h;
        let newLeft = rs.left;
        let newTop = rs.top;

        if (dir.includes('e')) newW = Math.max(MIN_WIDTH, rs.w + dx);
        if (dir.includes('w')) {
          newW = Math.max(MIN_WIDTH, rs.w - dx);
          newLeft = rs.left + (rs.w - newW);
        }
        if (dir.includes('s')) newH = Math.max(MIN_HEIGHT, rs.h + dy);
        if (dir.includes('n')) {
          newH = Math.max(MIN_HEIGHT, rs.h - dy);
          newTop = rs.top + (rs.h - newH);
        }

        setPanelSize({ w: newW, h: newH });
        setPanelPosition({ x: newLeft, y: newTop });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    isDraggingRef.current = isDragging;
    isResizingRef.current = isResizing;

    if (isDragging || isResizing) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }

    return cleanup;
  }, [isDragging, isResizing]);

  // useRef 同步状态，供事件回调读取最新值（避免闭包陈旧）
  const isDraggingRef = useRef(isDragging);
  isDraggingRef.current = isDragging;
  const isResizingRef = useRef(isResizing);
  isResizingRef.current = isResizing;

  // 不在打开状态时不渲染任何 UI
  if (!isOpen) return null;

  const tabs: { key: TabType; label: string }[] = [
    { key: 'trace', label: '链路追踪' },
    { key: 'audit', label: '审计日志' },
    { key: 'metrics', label: '监控指标' },
    { key: 'errors', label: '前端异常' },
  ];

  /** 渲染缩放把手 */
  const renderResizeHandles = () => (
    <>
      <div className="debug-resize-handle rh-n" onMouseDown={handleResizeStart('n')} />
      <div className="debug-resize-handle rh-s" onMouseDown={handleResizeStart('s')} />
      <div className="debug-resize-handle rh-w" onMouseDown={handleResizeStart('w')} />
      <div className="debug-resize-handle rh-e" onMouseDown={handleResizeStart('e')} />
      <div className="debug-resize-handle rh-nw" onMouseDown={handleResizeStart('nw')} />
      <div className="debug-resize-handle rh-ne" onMouseDown={handleResizeStart('ne')} />
      <div className="debug-resize-handle rh-sw" onMouseDown={handleResizeStart('sw')} />
      <div className="debug-resize-handle rh-se" onMouseDown={handleResizeStart('se')} />
    </>
  );

  return (
    <div className="debug-panel-overlay">
      <div
        className={`debug-panel ${panelPosition ? 'has-position' : ''}`}
        ref={panelRef}
        style={{
          width: panelSize.w,
          height: panelSize.h,
          ...(panelPosition ? { left: panelPosition.x, top: panelPosition.y } : {}),
        }}
      >
        {renderResizeHandles()}

        {/* 面板头部 - 可拖拽区域 */}
        <div
          className="debug-panel-header debug-drag-handle"
          onMouseDown={handleHeaderMouseDown}
        >
          <span className="debug-panel-title">诊断面板</span>
          <button
            className="debug-panel-close"
            onClick={() => useSystemStore.getState().setDiagnosticOpen(false)}
          >
            ✕
          </button>
        </div>

        {/* 标签页导航 */}
        <div className="debug-panel-tabs">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`debug-tab ${activeTab === tab.key ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 标签页内容 */}
        <div className="debug-panel-content">
          {activeTab === 'trace' && <TraceViewer />}
          {activeTab === 'audit' && <AuditLogViewer />}
          {activeTab === 'metrics' && <MetricsChart />}
          {activeTab === 'errors' && <FrontendErrorViewer />}
        </div>
      </div>
    </div>
  );
};

/**
 * DebugPanel: 诊断面板入口组件
 * 仅订阅 isDiagnosticOpen 状态，通过 props 传递给 DebugPanelInner。
 * 这样做确保 DebugPanelInner 的 hooks 在其 isOpen=true 时始终以相同顺序被调用。
 */
const DebugPanel: React.FC = () => {
  const isDiagnosticOpen = useSystemStore((s) => s.isDiagnosticOpen);
  return <DebugPanelInner isOpen={isDiagnosticOpen} />;
};

/**
 * FrontendErrorViewer: 前端异常日志查看器
 * 展示 systemStore 中缓冲的前端异常记录
 */
const FrontendErrorViewer: React.FC = () => {
  const frontendErrors = useSystemStore((s) => s.frontendErrors);

  return (
    <div className="frontend-error-viewer">
      <div className="error-header">
        <span>前端异常日志 ({frontendErrors.length}/100)</span>
        <button onClick={() => useSystemStore.getState().clearFrontendErrors()}>清空</button>
      </div>
      <div className="error-list">
        {frontendErrors.length === 0 ? (
          <div className="error-empty">暂无异常日志</div>
        ) : (
          Array.isArray(frontendErrors) && frontendErrors.map((err) => (
            <div key={err.id} className={`error-item level-${err.level.toLowerCase()}`}>
              <div className="error-item-header">
                <span className="error-time">{new Date(err.timestamp).toLocaleString()}</span>
                <span className="error-level">{err.level}</span>
                <span className="error-source">{err.source}</span>
              </div>
              <div className="error-message">{err.message}</div>
              {err.trace_id && <div className="error-trace">TraceID: {err.trace_id}</div>}
              {err.stack && <pre className="error-stack">{err.stack}</pre>}
              {err.component_stack && <pre className="error-stack">{err.component_stack}</pre>}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default DebugPanel;
