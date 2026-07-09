import React from 'react';
import { useSystemStore } from '../../stores/systemStore';
import './AnswerModeToggle.css';

export const AnswerModeToggle: React.FC = () => {
  const answerMode = useSystemStore((state) => state.answerMode);
  const setAnswerMode = useSystemStore((state) => state.setAnswerMode);

  const toggleAnswerMode = () => {
    setAnswerMode(answerMode === 'short' ? 'long' : 'short');
  };

  return (
    <div className="answer-mode-toggle-container">
      <div
        className={`answer-mode-segmented-control ${answerMode}`}
        onClick={toggleAnswerMode}
        title={answerMode === 'short' ? '普通模式：自然回复' : '长文模式：生成排版好的 Markdown 文稿'}
      >
        <div className="slider" />
        <div className={`segment-icon ${answerMode === 'short' ? 'active' : ''}`}>
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
            <path d="M4 6h16M4 12h10M4 18h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>
        <div className={`segment-icon ${answerMode === 'long' ? 'active' : ''}`}>
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
            <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>
      </div>
    </div>
  );
};
