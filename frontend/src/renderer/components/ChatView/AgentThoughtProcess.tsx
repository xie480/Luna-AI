import React, { useState } from 'react';
import { RagThoughtEvent } from '../../../types/rag';
import './AgentThoughtProcess.css';

interface AgentThoughtProcessProps {
  thoughts: RagThoughtEvent[];
}

export const AgentThoughtProcess: React.FC<AgentThoughtProcessProps> = ({ thoughts }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (thoughts.length === 0) return null;

  // We only show if there are thoughts.
  // When completed (if that concept is tracked by thoughts array size or final thought stage),
  // we might want to auto-collapse. For now, we'll keep it simple.

  const isGenerating = thoughts.some(t => t.stage === 'generating');
  const displayThoughts = isExpanded ? thoughts : thoughts.slice(-1);

  if (isGenerating && !isExpanded) {
    return (
      <div 
        className="agent-thought-process collapsed cursor-pointer"
        onClick={() => setIsExpanded(true)}
      >
        <span className="expand-icon">[+]</span> 展开 {thoughts.length} 步认知检索过程
      </div>
    );
  }

  return (
    <div className="agent-thought-process">
      {thoughts.length > 1 && isExpanded && (
        <div 
          className="collapse-header cursor-pointer"
          onClick={() => setIsExpanded(false)}
        >
          <span className="expand-icon">[-]</span> 收起过程
        </div>
      )}
      <div className="thought-list">
        {displayThoughts.map((t, idx) => (
          <div key={idx} className={`thought-item ${t.stage}`}>
            <span className="thought-icon">
              {t.stage === 'generating' ? '💬' :
               t.stage === 'searching' ? '🔍' :
               t.stage === 'evaluating' ? '⚖️' :
               t.stage === 'rewriting' ? '🔄' : '✓'}
            </span>
            <span className="thought-text" onMouseDown={(e) => e.stopPropagation()}>{t.description}</span>
          </div>
        ))}
        {!isGenerating && !isExpanded && thoughts.length > 0 && (
          <div className="thought-item active-pulse">
            <span className="thought-icon">⏳</span>
            <span className="thought-text" onMouseDown={(e) => e.stopPropagation()}>意图分析中...</span>
          </div>
        )}
      </div>
    </div>
  );
};
