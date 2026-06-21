/**
 * DagCanvas — 可交互画布容器。
 * 做什么：提供无限画布的缩放和平移能力，作为 DagStateGroup 的布局容器。
 * 为什么这样做：DAG 工作流可能包含多个 State 和大量 Node，需要画布级别的缩放和平移来浏览。
 * 输入输出：子组件通过 children 传入，画布状态由 dagWorkflowStore 管理。
 * 边界条件：缩放范围 0.3x ~ 3.0x，双击重置到默认视图。
 * 异常行为：无。
 */
import React, { useRef, useCallback, useEffect, useState } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import './DagCanvas.css';

/**
 * 画布容器组件。
 */
export const DagCanvas: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const canvasZoom = useDagWorkflowStore((state) => state.canvasZoom);
  const canvasOffset = useDagWorkflowStore((state) => state.canvasOffset);
  const setCanvasZoom = useDagWorkflowStore((state) => state.setCanvasZoom);
  const setCanvasOffset = useDagWorkflowStore((state) => state.setCanvasOffset);

  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [offsetStart, setOffsetStart] = useState({ x: 0, y: 0 });

  /**
   * 处理鼠标滚轮缩放。
   * 做什么：根据滚轮方向增减缩放比例。
   * 为什么这样做：用户需要通过滚轮快速缩放画布查看细节或全局。
   */
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      setCanvasZoom(canvasZoom + delta);
    },
    [canvasZoom, setCanvasZoom],
  );

  /**
   * 处理鼠标按下开始拖拽。
   * 做什么：记录拖拽起始位置和当前偏移。
   * 为什么这样做：用户需要通过拖拽画布空白区域来平移视图。
   */
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      // 只响应左键点击画布空白区域
      if (e.button !== 0) return;
      if (e.target !== containerRef.current && !(e.target as HTMLElement).classList.contains('dag-canvas-inner')) return;
      setIsDragging(true);
      setDragStart({ x: e.clientX, y: e.clientY });
      setOffsetStart({ ...canvasOffset });
    },
    [canvasOffset],
  );

  /**
   * 处理鼠标移动拖拽。
   * 做什么：更新画布偏移量。
   */
  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return;
      const dx = e.clientX - dragStart.x;
      const dy = e.clientY - dragStart.y;
      setCanvasOffset({
        x: offsetStart.x + dx,
        y: offsetStart.y + dy,
      });
    },
    [isDragging, dragStart, offsetStart, setCanvasOffset],
  );

  /**
   * 处理鼠标释放结束拖拽。
   */
  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  /**
   * 双击重置画布到默认视图。
   * 做什么：将缩放和偏移重置为初始值。
   * 为什么这样做：用户在缩放和平移后需要快速回到全局视图。
   */
  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      // 只响应画布空白区域的双击
      if (e.target !== containerRef.current && !(e.target as HTMLElement).classList.contains('dag-canvas-inner')) return;
      setCanvasZoom(1);
      setCanvasOffset({ x: 0, y: 0 });
    },
    [setCanvasZoom, setCanvasOffset],
  );

  // 全局 mouseup 监听，防止鼠标移出画布区域后拖拽状态残留
  useEffect(() => {
    if (!isDragging) return;
    const handleGlobalUp = () => setIsDragging(false);
    window.addEventListener('mouseup', handleGlobalUp);
    return () => window.removeEventListener('mouseup', handleGlobalUp);
  }, [isDragging]);

  return (
    <div
      ref={containerRef}
      className={`dag-canvas-container ${isDragging ? 'is-dragging' : ''}`}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onDoubleClick={handleDoubleClick}
    >
      <div
        className="dag-canvas-inner"
        style={{
          transform: `scale(${canvasZoom}) translate(${canvasOffset.x / canvasZoom}px, ${canvasOffset.y / canvasZoom}px)`,
          transformOrigin: 'top left',
        }}
      >
        {children}
      </div>
    </div>
  );
};
