import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { CHAT_WORKFLOW_NODE_TYPE } from '../../../shared/enum';
import './HolographicARPanel.css';

interface HolographicARPanelProps {
  nodeType: string;
  interactionId: string;
  targetRect: DOMRect;
  containerRect?: DOMRect;
  onClose: () => void;
}

const CONDITION_NODE_TYPES = new Set<string>([
  CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG,
  CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG,
]);

export const HolographicARPanel: React.FC<HolographicARPanelProps> = ({
  nodeType,
  interactionId,
  targetRect,
  containerRect,
  onClose,
}) => {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [typedText, setTypedText] = useState('');
  const dragStartPos = useRef({ x: 0, y: 0 });
  const panelRef = useRef<HTMLDivElement>(null);

  const latestConditionResults = useChatWorkflowStore((state) => state.latestConditionResults);
  const debugTimelineByTraceId = useChatWorkflowStore((state) => state.debugTimelineByTraceId);
  const activePlan = useChatWorkflowStore((state) => state.activePlan);

  const fullText = useMemo(() => {
    if (CONDITION_NODE_TYPES.has(nodeType)) {
      const conditionKey = `${interactionId}:${nodeType}`;
      const result = latestConditionResults[conditionKey];
      if (!result) {
        return '> Route Evaluation Pending or Skipped...';
      }
      return [
        '> Route Evaluated',
        `> Source: ${result.sourceNodeType}`,
        `> Target: ${result.targetNodeType}`,
        `> Entered: ${String(result.conditionEntered)}`,
        '> Reason:',
        result.reason,
      ].join('\n');
    }

    if (activePlan?.traceId) {
      const timeline = debugTimelineByTraceId[activePlan.traceId];
      if (timeline) {
        const nodeEvents = timeline.events.filter((event) => event.nodeType === nodeType);
        if (nodeEvents.length > 0) {
          return nodeEvents
            .map((event) => {
              const timeText = new Date(event.timestampMs).toLocaleTimeString();
              return `[${timeText}] ${event.title}\n${event.detail}`;
            })
            .join('\n\n');
        }
      }
    }

    return '> 暂无可展示的详细追踪信息';
  }, [activePlan?.traceId, debugTimelineByTraceId, interactionId, latestConditionResults, nodeType]);

  const initialPosition = useMemo(() => {
    if (!containerRect) {
      return { x: 0, y: 0 };
    }

    const panelWidth = 320;
    const panelHeight = panelRef.current?.offsetHeight ?? 180;
    let left = targetRect.right + 20;
    let top = targetRect.top;

    if (left + panelWidth > window.innerWidth) {
      left = targetRect.left - panelWidth - 16;
    }
    if (left < 8) {
      left = 8;
    }
    if (top + panelHeight > window.innerHeight) {
      top = Math.max(8, window.innerHeight - panelHeight - 8);
    }

    return { x: left, y: top };
  }, [containerRect, targetRect.bottom, targetRect.left, targetRect.right, targetRect.top]);

  const currentPosition = position ?? initialPosition;

  useEffect(() => {
    setPosition(null);
  }, [initialPosition.x, initialPosition.y, nodeType]);

  useEffect(() => {
    setTypedText('');
    if (!fullText) {
      return;
    }

    let cancelled = false;
    let currentIndex = 0;
    let timerId: number | null = null;

    const typeNextCharacter = () => {
      if (cancelled) {
        return;
      }
      currentIndex = Math.min(currentIndex + 1, fullText.length);
      setTypedText(fullText.slice(0, currentIndex));
      if (currentIndex < fullText.length) {
        timerId = window.setTimeout(typeNextCharacter, 10);
      }
    };

    timerId = window.setTimeout(typeNextCharacter, 10);

    return () => {
      cancelled = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    };
  }, [fullText]);

  const handleMouseDown = (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();

    setPosition(currentPosition);
    setIsDragging(true);
    dragStartPos.current = {
      x: event.clientX - currentPosition.x,
      y: event.clientY - currentPosition.y,
    };
  };

  useEffect(() => {
    if (!isDragging) {
      return;
    }

    const handleMouseMove = (event: MouseEvent) => {
      const panelWidth = panelRef.current?.offsetWidth ?? 320;
      const panelHeight = panelRef.current?.offsetHeight ?? 180;
      const nextX = Math.min(
        Math.max(8, event.clientX - dragStartPos.current.x),
        Math.max(8, window.innerWidth - panelWidth - 8),
      );
      const nextY = Math.min(
        Math.max(8, event.clientY - dragStartPos.current.y),
        Math.max(8, window.innerHeight - panelHeight - 8),
      );
      setPosition({ x: nextX, y: nextY });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    document.body.style.userSelect = 'none';

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.body.style.userSelect = '';
    };
  }, [isDragging]);

  if (!containerRect) {
    return null;
  }

  return createPortal(
    <div
      className="holographic-ar-panel"
      style={{
        left: `${currentPosition.x}px`,
        top: `${currentPosition.y}px`,
        cursor: isDragging ? 'grabbing' : 'auto',
      }}
      onClick={(event) => event.stopPropagation()}
      ref={panelRef}
    >
      <div
        className="ar-panel-header"
        onMouseDown={handleMouseDown}
        style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
      >
        <span className="ar-title">SYS.TRACE // {nodeType.toUpperCase()}</span>
        <button className="ar-close-btn" onClick={onClose}>×</button>
      </div>
      <div className="ar-panel-body">
        <div className="scanline-overlay" />
        <pre className="typewriter-text">{typedText}</pre>
      </div>
    </div>,
    document.body,
  );
};
