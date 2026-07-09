import React, { useRef } from 'react';
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
      <button
        className={`answer-mode-capsule ${answerMode === 'long' ? 'mode-long' : 'mode-short'}`}
        onClick={toggleAnswerMode}
        title={answerMode === 'short' ? '短回答模式 (点击切换)' : '长回答模式 (点击切换)'}
      >
        <span className="capsule-icon">
          {answerMode === 'short' ? (
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
              <path d="M4 6h16M4 12h10M4 18h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
              <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          )}
        </span>
        <span className="capsule-label">{answerMode === 'short' ? '短' : '长'}</span>
      </button>
    </div>
  );
};
