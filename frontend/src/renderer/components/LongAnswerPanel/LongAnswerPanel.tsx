import React from 'react';
import './LongAnswerPanel.css';
import { LongAnswerHeader } from './LongAnswerHeader';
import { LongAnswerMarkdown } from './LongAnswerMarkdown';
import { LongAnswerToolbar } from './LongAnswerToolbar';
import { LongAnswerResizeHandles } from './LongAnswerResizeHandles';
import { useLongAnswerStore } from '../../stores/longAnswerStore';
import { useLongAnswerDragResize } from './useLongAnswerDragResize';

export const LongAnswerPanel: React.FC = () => {
  const panelState = useLongAnswerStore((state) => state.panel);
  const activeId = useLongAnswerStore((state) => state.activeId);
  const item = useLongAnswerStore((state) =>
    activeId ? state.byId[activeId] : null
  );
  
  const { handlePointerDown, handlePointerMove, handlePointerUp } = useLongAnswerDragResize();

  if (!panelState.visible || !item) {
    return null;
  }

  // Handle CSS variable setup for transforms and dimensions
  const style: React.CSSProperties = {
    transform: `translate3d(${panelState.x}px, ${panelState.y}px, 0)`,
    width: `${panelState.width}px`,
    height: `${panelState.height}px`,
    // Ensure visibility
    display: 'flex',
    visibility: 'visible',
    opacity: 1,
    // If the window is narrow, switch to full-width drawer mode via CSS media queries,
    // but the inline style will still be applied. Let's make inline style dynamic if needed,
    // though usually CSS overrides inline with !important or we handle it in render logic.
    // We will let CSS handle mobile overrides via media queries by using classes.
  };

  // console.log("LongAnswerPanel Render Debug:", { panelState, item });

  return (
    <div
      className={`long-answer-panel ${panelState.isDragging ? 'dragging' : ''} ${panelState.isResizing ? 'resizing' : ''}`}
      style={style}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp} // In case pointer goes outside the panel, though pointer capture usually handles this
    >
      <LongAnswerHeader item={item} onPointerDown={handlePointerDown} />
      
      <div className="long-answer-body">
        <LongAnswerMarkdown markdown={item.markdown} status={item.status} />
        {item.citations && item.citations.length > 0 && (
          <div className="long-answer-sources">
            {/* Minimal source list rendering for now */}
            <h4>参考来源</h4>
            <ul>
              {item.citations.map((c, i) => (
                <li key={i}>[{c.citation_id || i + 1}] {c.document_name || '未知来源'}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <LongAnswerToolbar item={item} />
      
      <LongAnswerResizeHandles onPointerDown={handlePointerDown} />
    </div>
  );
};
