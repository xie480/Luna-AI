import React from 'react';
import { useHistoryStore } from '../../stores/historyStore';
import { ChatHistoryView } from './ChatHistoryView';
import './PhoneMockup.css';

export const PhoneMockup: React.FC = () => {
  const { setSelectedDate } = useHistoryStore();

  return (
    <div className="phone-mockup">
      <div className="phone-frame">
        <div className="dynamic-island">
          <div className="camera-lens"></div>
          <div className="sensor"></div>
        </div>
        <div className="phone-screen">
          <div className="phone-header">
            <button className="back-btn" onClick={() => setSelectedDate(null)}>
              <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"></polyline>
              </svg>
              <span>返回</span>
            </button>
            <div className="dynamic-island-placeholder"></div>
          </div>
          <ChatHistoryView />
        </div>
      </div>
    </div>
  );
};
