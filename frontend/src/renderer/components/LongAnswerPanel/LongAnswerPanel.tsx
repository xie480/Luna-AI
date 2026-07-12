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

  // Handle CSS variable setup for transforms and dimensions
  const style: React.CSSProperties = {
    '--x': `${panelState.x}px`,
    '--y': `${panelState.y}px`,
    width: `${panelState.width}px`,
    height: `${panelState.height}px`,
    display: 'flex',
  } as React.CSSProperties;

  // console.log("LongAnswerPanel Render Debug:", { panelState, item });

  return (
    <div
      className={`long-answer-panel ${panelState.visible && item ? 'visible' : ''} ${panelState.isDragging ? 'dragging' : ''} ${panelState.isResizing ? 'resizing' : ''}`}
      style={style}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp} // In case pointer goes outside the panel, though pointer capture usually handles this
    >
      {item && (
        <>
          <LongAnswerHeader item={item} onPointerDown={handlePointerDown} />
          
          <div className="long-answer-body" onPointerDown={(e) => e.stopPropagation()}>
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
        </>
      )}
    </div>
  );
};
