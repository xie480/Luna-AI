import React, { useState } from 'react';
import { FileUploadDropzone, UrlScrapeInput, IngestionProgress, StrategyDebugger, PendingItemsList, GlobalSubmitButton } from './Ingestion/Ingestion';
import { KnowledgeFilter, KnowledgeTable } from './KnowledgeList/KnowledgeList';
import './KnowledgeBasePanel.css';

export const KnowledgeBasePanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'ingestion' | 'list'>('list');

  return (
    <div className="knowledge-base-panel">
      <div className="settings-sidebar">
        <div
          className={`settings-nav-item ${activeTab === 'list' ? 'active' : ''}`}
          onClick={() => setActiveTab('list')}
        >
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"></path>
            </svg>
          </span>
          <span className="nav-text">知识库管理</span>
        </div>
        <div
          className={`settings-nav-item ${activeTab === 'ingestion' ? 'active' : ''}`}
          onClick={() => setActiveTab('ingestion')}
        >
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
          </span>
          <span className="nav-text">添加知识</span>
        </div>
      </div>
      
      <div className="settings-content">
        {activeTab === 'list' && (
          <div className="settings-content-section">
            <h3 className="settings-section-title">已入库知识</h3>
            <KnowledgeFilter />
            <KnowledgeTable />
          </div>
        )}

        {activeTab === 'ingestion' && (
          <div className="settings-content-section">
            <h3 className="settings-section-title">添加知识</h3>
            <FileUploadDropzone />
            <UrlScrapeInput />
            <PendingItemsList />
            <IngestionProgress />
            <StrategyDebugger />
            <GlobalSubmitButton />
          </div>
        )}
      </div>
    </div>
  );
};
