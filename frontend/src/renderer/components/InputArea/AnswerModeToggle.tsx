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
      >
        <div className="slider" />
        <div className={`segment-icon ${answerMode === 'short' ? 'active' : ''}`}>
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
            <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M8 12h8M8 8h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <div className={`segment-icon ${answerMode === 'long' ? 'active' : ''}`}>
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="14" height="14">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </div>
    </div>
  );
};
