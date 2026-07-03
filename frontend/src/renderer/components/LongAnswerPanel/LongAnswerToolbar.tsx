import React, { useState } from 'react';
import { LongAnswerItem } from '../../shared/types';
import { useLongAnswerStore } from '../../stores/longAnswerStore';

interface LongAnswerToolbarProps {
  item: LongAnswerItem;
}

export const LongAnswerToolbar: React.FC<LongAnswerToolbarProps> = ({ item }) => {
  const [copied, setCopied] = useState(false);
  const closePanel = useLongAnswerStore((state) => state.closePanel);
  const setPanelState = useLongAnswerStore((state) => state.setPanelState);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(item.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  const handleScrollToBottom = () => {
    // A bit hacky, but effective given the structure. Better approach is to use refs passed down or context.
    const container = document.querySelector('.long-answer-markdown-container');
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  };

  const handleRetry = () => {
    // Invoke API to retry. This needs to be hooked up to longAnswerService
    console.log('Retry triggered for', item.id);
  };

  const isFailed = item.status === 'FAILED';
  const isCompleted = item.status === 'COMPLETED';

  return (
    <div className="long-answer-toolbar">
      <div className="toolbar-left">
        {isFailed ? (
          <button className="toolbar-btn primary" onClick={handleRetry}>
            重试整理
          </button>
        ) : (
          <button className="toolbar-btn" onClick={handleCopy} disabled={!item.markdown}>
            {copied ? '已复制' : '复制全文'}
          </button>
        )}
        
        {isCompleted && item.citations && item.citations.length > 0 && (
          <button className="toolbar-btn outline">查看来源</button>
        )}
      </div>

      <div className="toolbar-right">
        <button className="toolbar-btn icon-only" onClick={handleScrollToBottom} title="回到底部">
          ↓
        </button>
        <button className="toolbar-btn" onClick={closePanel}>
          收起
        </button>
      </div>
    </div>
  );
};
