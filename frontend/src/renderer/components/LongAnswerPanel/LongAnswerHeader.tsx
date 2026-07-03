import React from 'react';
import { LongAnswerItem } from '../../shared/types';
import { useLongAnswerStore } from '../../stores/longAnswerStore';

interface LongAnswerHeaderProps {
  item: LongAnswerItem;
  onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
}

export const LongAnswerHeader: React.FC<LongAnswerHeaderProps> = ({ item, onPointerDown }) => {
  const closePanel = useLongAnswerStore((state) => state.closePanel);

  const getStatusText = () => {
    switch (item.status) {
      case 'PENDING':
      case 'GENERATING':
      case 'SUMMARY_GENERATING':
        return 'Luna正在整理中……';
      case 'FAILED':
        return '整理中断了';
      case 'COMPLETED':
        return item.title || '整理完成';
      default:
        return item.title || '文档';
    }
  };

  const getStatusClass = () => {
    switch (item.status) {
      case 'PENDING':
      case 'GENERATING':
      case 'SUMMARY_GENERATING':
        return 'status-generating';
      case 'FAILED':
        return 'status-failed';
      case 'COMPLETED':
        return 'status-completed';
      default:
        return '';
    }
  };

  return (
    <div 
      className="long-answer-header long-answer-header-drag-handle" 
      onPointerDown={onPointerDown}
    >
      <div className={`long-answer-status-dot ${getStatusClass()}`} />
      
      <div className="long-answer-title-container">
        <h3 className="long-answer-title" title={getStatusText()}>
          {getStatusText()}
        </h3>
        {item.status === 'GENERATING' && (
          <span className="long-answer-subtitle">正在生成内容</span>
        )}
      </div>

      <div className="long-answer-header-actions">
        {/* Placeholder for standard window controls like copy/minimize */}
        <button 
          className="long-answer-close-btn" 
          onClick={closePanel}
          title="关闭面板"
          aria-label="关闭面板"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>
  );
};
