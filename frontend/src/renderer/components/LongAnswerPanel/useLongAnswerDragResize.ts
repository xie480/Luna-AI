import { useState, useCallback, useRef, useEffect } from 'react';
import { useLongAnswerStore } from '../../stores/longAnswerStore';

interface UseLongAnswerDragResizeOptions {
  minWidth?: number;
  minHeight?: number;
  maxWidth?: number | (() => number);
  maxHeight?: number | (() => number);
  dragHandleSelector?: string;
}

export function useLongAnswerDragResize(options: UseLongAnswerDragResizeOptions = {}) {
  const {
    minWidth = 360,
    minHeight = 320,
    maxWidth = () => Math.min(900, window.innerWidth * 0.9),
    maxHeight = () => window.innerHeight - 72,
    dragHandleSelector = '.long-answer-header-drag-handle',
  } = options;

  const panelState = useLongAnswerStore((state) => state.panel);
  const setPanelState = useLongAnswerStore((state) => state.setPanelState);

  const dragState = useRef({
    startX: 0,
    startY: 0,
    initialX: 0,
    initialY: 0,
    initialWidth: 0,
    initialHeight: 0,
    isDragging: false,
    isResizing: false,
    resizeDirection: '' as string,
  });

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // Check if clicking on resize handles
      const target = e.target as HTMLElement;
      if (target.classList.contains('resize-handle')) {
        e.preventDefault();
        e.stopPropagation();
        
        target.setPointerCapture(e.pointerId);
        
        dragState.current = {
          ...dragState.current,
          startX: e.clientX,
          startY: e.clientY,
          initialX: panelState.x,
          initialY: panelState.y,
          initialWidth: panelState.width,
          initialHeight: panelState.height,
          isResizing: true,
          resizeDirection: target.dataset.direction || '',
        };
        
        setPanelState({ isResizing: true });
        return;
      }

      // Check if clicking on drag handle
      if (target.closest(dragHandleSelector)) {
        // Don't drag if clicking buttons
        if (target.closest('button')) return;

        e.preventDefault();
        target.setPointerCapture(e.pointerId);

        dragState.current = {
          ...dragState.current,
          startX: e.clientX,
          startY: e.clientY,
          initialX: panelState.x,
          initialY: panelState.y,
          isDragging: true,
        };

        setPanelState({ isDragging: true });
      }
    },
    [panelState.x, panelState.y, panelState.width, panelState.height, setPanelState, dragHandleSelector]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragState.current.isDragging && !dragState.current.isResizing) return;

      const deltaX = e.clientX - dragState.current.startX;
      const deltaY = e.clientY - dragState.current.startY;

      if (dragState.current.isDragging) {
        // Calculate new position with bounds
        let newX = dragState.current.initialX + deltaX;
        let newY = dragState.current.initialY + deltaY;

        // Basic bounds checking (keep at least partially visible)
        const maxX = window.innerWidth - 80;
        const maxY = window.innerHeight - 48;
        
        newX = Math.max(-panelState.width + 80, Math.min(newX, maxX));
        newY = Math.max(0, Math.min(newY, maxY));

        setPanelState({ x: newX, y: newY });
      } else if (dragState.current.isResizing) {
        const dir = dragState.current.resizeDirection;
        let newWidth = dragState.current.initialWidth;
        let newHeight = dragState.current.initialHeight;

        const resolvedMaxWidth = typeof maxWidth === 'function' ? maxWidth() : maxWidth;
        const resolvedMaxHeight = typeof maxHeight === 'function' ? maxHeight() : maxHeight;

        if (dir.includes('e')) {
          newWidth = Math.max(minWidth, Math.min(dragState.current.initialWidth + deltaX, resolvedMaxWidth));
        }
        if (dir.includes('s')) {
          newHeight = Math.max(minHeight, Math.min(dragState.current.initialHeight + deltaY, resolvedMaxHeight));
        }

        setPanelState({ width: newWidth, height: newHeight });
      }
    },
    [setPanelState, panelState.width, maxWidth, maxHeight, minWidth, minHeight]
  );

  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (dragState.current.isDragging || dragState.current.isResizing) {
        const target = e.target as HTMLElement;
        target.releasePointerCapture(e.pointerId);
        
        dragState.current.isDragging = false;
        dragState.current.isResizing = false;
        
        setPanelState({ isDragging: false, isResizing: false });
      }
    },
    [setPanelState]
  );

  // Handle window resize to ensure panel stays in view
  useEffect(() => {
    const handleResize = () => {
      const maxX = window.innerWidth - 80;
      if (panelState.x > maxX) {
        setPanelState({ x: Math.max(0, maxX) });
      }
      
      const resolvedMaxWidth = typeof maxWidth === 'function' ? maxWidth() : maxWidth;
      if (panelState.width > resolvedMaxWidth) {
        setPanelState({ width: resolvedMaxWidth });
      }
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [panelState.x, panelState.width, setPanelState, maxWidth]);

  return {
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
  };
}
