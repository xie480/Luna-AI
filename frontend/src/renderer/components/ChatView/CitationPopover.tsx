import React, { useState } from 'react';
import { useFloating, useInteractions, useHover, useFocus, useDismiss, offset, shift, flip, autoUpdate } from '@floating-ui/react';
import { RagEvidence } from '../../../types/rag';
import { useSystemStore } from '../../../stores/systemStore';
import './CitationPopover.css';

interface CitationPopoverProps {
  index: number;
  citationId: number;
  docId: string;
  chunkId: string;
  citations: RagEvidence[];
}

export const CitationPopover: React.FC<CitationPopoverProps> = ({ index, citationId, docId, chunkId, citations }) => {
  const [isOpen, setIsOpen] = useState(false);
  const evidence = citations.find(c => c.citation_id === citationId || c.chunk_id === chunkId);
  const addSystemLog = useSystemStore(state => state.addSystemLog);

  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement: 'top-start',
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(8),
      flip(),
      shift({ padding: 8 })
    ]
  });

  const hover = useHover(context, { move: false });
  const focus = useFocus(context);
  const dismiss = useDismiss(context);

  const { getReferenceProps, getFloatingProps } = useInteractions([
    hover,
    focus,
    dismiss
  ]);

  const handleOpenSourceText = () => {
    setIsOpen(false);
    // Future enhancement: Open full source text modal
    addSystemLog(`打开了引用 [${index}] 的原始片段查看，Doc ID: ${docId}, Chunk ID: ${chunkId}`);
  };

  return (
    <>
      <sup 
        className="citation-badge"
        ref={refs.setReference}
        {...getReferenceProps()}
      >
        [{index}]
      </sup>
      
      {isOpen && evidence && (
        <div 
          className="citation-popover-panel"
          ref={refs.setFloating}
          style={floatingStyles}
          {...getFloatingProps()}
        >
          <div className="citation-header">
            <span className="citation-doc-name" title={evidence.document_name}>📄 {evidence.document_name}</span>
            <span className="citation-score">{(evidence.score * 100).toFixed(1)}%</span>
          </div>
          <div className="citation-content-preview selectable-text" onMouseDown={(e) => e.stopPropagation()}>
            {evidence.content}
          </div>
          <div className="citation-footer">
            <button className="btn-view-source" onClick={handleOpenSourceText}>
              查看完整原文
            </button>
          </div>
        </div>
      )}
    </>
  );
};
