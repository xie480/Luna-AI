import React, { useState } from 'react';
import { ManualMemory } from './ManualMemory';
import { MemoryViewer } from './MemoryViewer';
import './MemoryPanel.css';

type MemoryTab = 'manual' | 'viewer';

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
          <span className="nav-icon">📦</span>
          <span className="nav-text">手动记忆</span>
        </div>
        <div
          className={`memory-nav-item ${activeTab === 'viewer' ? 'active' : ''}`}
          onClick={() => setActiveTab('viewer')}
        >
          <span className="nav-icon">🧠</span>
          <span className="nav-text">记忆查看</span>
        </div>
      </div>
      <div className="memory-content">
        {renderContent()}
      </div>
    </div>
  );
};
