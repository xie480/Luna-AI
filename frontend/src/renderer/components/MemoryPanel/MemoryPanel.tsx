import React, { useState } from 'react';
import { ManualMemory } from './ManualMemory';
import { MemoryViewer } from './MemoryViewer';
import './MemoryPanel.css';

type MemoryTab = 'manual' | 'viewer';

/** 手动记忆图标 - 三层结构/数据库风格 */
const ManualMemoryIcon: React.FC = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="12" cy="5" rx="9" ry="3"/>
    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
  </svg>
);

/** 记忆查看图标 - 眼睛/列表风格 */
const MemoryViewerIcon: React.FC = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
    <circle cx="12" cy="12" r="3"/>
  </svg>
);

export const MemoryPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<MemoryTab>('manual');

  const renderContent = () => {
    switch (activeTab) {
      case 'manual':
        return <ManualMemory />;
      case 'viewer':
        return <MemoryViewer />;
      default:
        return null;
    }
  };

  return (
    <div className="memory-panel-container">
      <div className="memory-sidebar">
        <div
          className={`memory-nav-item ${activeTab === 'manual' ? 'active' : ''}`}
          onClick={() => setActiveTab('manual')}
        >
          <ManualMemoryIcon />
          <span className="nav-text">手动记忆</span>
        </div>
        <div
          className={`memory-nav-item ${activeTab === 'viewer' ? 'active' : ''}`}
          onClick={() => setActiveTab('viewer')}
        >
          <MemoryViewerIcon />
          <span className="nav-text">记忆查看</span>
        </div>
      </div>
      <div className="memory-content">
        {renderContent()}
      </div>
    </div>
  );
};
