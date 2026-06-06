import React, { useState } from 'react';
import { GeneralSettings } from './GeneralSettings';
import { ApiConfigPresetPanel } from './ApiConfigPresetPanel';
import { EnvSettings } from './EnvSettings';
import './SettingsPanel.css';

import { KnowledgeBasePanel } from '../KnowledgeBase/KnowledgeBasePanel';

type SettingsTab = 'general' | 'knowledge' | 'api' | 'env';

export const SettingsPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');

  const renderContent = () => {
    switch (activeTab) {
      case 'general':
        return <GeneralSettings />;
      case 'knowledge':
        return <KnowledgeBasePanel />;
      case 'api':
        return (
          <div className="settings-content-section">
            <h3 className="settings-section-title">API 配置</h3>
            <ApiConfigPresetPanel />
          </div>
        );
      case 'env':
        return <EnvSettings />;
      default:
        return null;
    }
  };

  return (
    <div className="settings-panel-container">
      <div className="settings-sidebar">
        <div
          className={`settings-nav-item ${activeTab === 'general' ? 'active' : ''}`}
          onClick={() => setActiveTab('general')}
        >
          <span className="nav-icon">⚙️</span>
          <span className="nav-text">通用</span>
        </div>
        <div
          className={`settings-nav-item ${activeTab === 'knowledge' ? 'active' : ''}`}
          onClick={() => setActiveTab('knowledge')}
        >
          <span className="nav-icon">📚</span>
          <span className="nav-text">知识库</span>
        </div>
        <div
          className={`settings-nav-item ${activeTab === 'api' ? 'active' : ''}`}
          onClick={() => setActiveTab('api')}
        >
          <span className="nav-icon">🔌</span>
          <span className="nav-text">API</span>
        </div>
        <div
          className={`settings-nav-item ${activeTab === 'env' ? 'active' : ''}`}
          onClick={() => setActiveTab('env')}
        >
          <span className="nav-icon">📝</span>
          <span className="nav-text">环境配置</span>
        </div>
      </div>
      <div className="settings-content">
        {renderContent()}
      </div>
    </div>
  );
};
