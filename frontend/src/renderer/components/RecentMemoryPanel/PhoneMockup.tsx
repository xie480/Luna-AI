import React from 'react';
import { ChatHistoryView } from './ChatHistoryView';
import './PhoneMockup.css';

export const PhoneMockup: React.FC = () => {
  return (
    <div className="phone-mockup">
      <div className="phone-frame">
        <div className="dynamic-island">
          <div className="camera-lens"></div>
          <div className="sensor"></div>
        </div>
        <div className="phone-screen">
          <ChatHistoryView />
        </div>
      </div>
    </div>
  );
};
