import React, { useState } from 'react';
import { FileUploadDropzone, UrlScrapeInput, IngestionProgress, StrategyDebugger, PendingItemsList, GlobalSubmitButton } from './Ingestion/Ingestion';
import { KnowledgeFilter, KnowledgeTable } from './KnowledgeList/KnowledgeList';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import './KnowledgeBasePanel.css';

export const KnowledgeBasePanel: React.FC = () => {
  const documentToUpdate = useKnowledgeStore(state => state.documentToUpdate);
  const setDocumentToUpdate = useKnowledgeStore(state => state.setDocumentToUpdate);
  // 'update' tab means we are browsing the list of updatable (active/completed) documents
  const [activeTab, setActiveTab] = useState<'ingestion' | 'list' | 'update'>('list');

  const handleSwitchToList = () => {
    setActiveTab('list');
    setDocumentToUpdate(null);
  };

  const handleSwitchToIngestion = () => {
    setActiveTab('ingestion');
    setDocumentToUpdate(null);
  };

  const handleSwitchToUpdate = () => {
    setActiveTab('update');
    setDocumentToUpdate(null);
  };

  return (
    <div className="knowledge-base-panel">
      <div className="settings-sidebar">
        <div
          className={`settings-nav-item ${activeTab === 'list' ? 'active' : ''}`}
          onClick={handleSwitchToList}
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
          onClick={handleSwitchToIngestion}
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
        <div
          className={`settings-nav-item ${activeTab === 'update' ? 'active' : ''}`}
          onClick={handleSwitchToUpdate}
        >
          <span className="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="1 4 1 10 7 10"></polyline>
              <polyline points="23 20 23 14 17 14"></polyline>
              <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"></path>
            </svg>
          </span>
          <span className="nav-text">更新知识</span>
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

        {activeTab === 'update' && !documentToUpdate && (
          <div className="settings-content-section">
            <h3 className="settings-section-title">请选择要更新的文档</h3>
            <KnowledgeFilter forceStatus="completed" />
            <KnowledgeTable isUpdateSelectorMode={true} />
          </div>
        )}

        {activeTab === 'update' && documentToUpdate && (
          <div className="settings-content-section">
            <div className="settings-section-header">
              <h3 className="settings-section-title">更新知识文档</h3>
              <button
                className="btn-action"
                onClick={handleSwitchToUpdate}
              >
                返回列表
              </button>
            </div>
            
            <div className="update-context-info">
              <div className="update-context-title">正在更新目标文档</div>
              <div className="update-context-meta">
                <span className="flex items-center gap-1">
                  {documentToUpdate.source_type === 'local_file' ? (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      <polyline points="14 2 14 8 20 8"></polyline>
                      <line x1="16" y1="13" x2="8" y2="13"></line>
                      <line x1="16" y1="17" x2="8" y2="17"></line>
                      <polyline points="10 9 9 9 8 9"></polyline>
                    </svg>
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"></circle>
                      <line x1="2" y1="12" x2="22" y2="12"></line>
                      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                    </svg>
                  )}
                  {documentToUpdate.filename}
                </span>
                <span>·</span>
                <span>{documentToUpdate.estimated_tokens > 0 ? `${documentToUpdate.estimated_tokens} Tokens` : '计算中...'}</span>
              </div>
            </div>

            {documentToUpdate.source_type === 'local_file' && <FileUploadDropzone isUpdateMode={true} targetDocId={documentToUpdate.id} />}
            {documentToUpdate.source_type === 'url' && <UrlScrapeInput isUpdateMode={true} targetDocId={documentToUpdate.id} />}
            <PendingItemsList isUpdateMode={true} />
            <StrategyDebugger disabled={true} />
            <GlobalSubmitButton isUpdateMode={true} targetDocId={documentToUpdate.id} />
          </div>
        )}
      </div>
    </div>
  );
};
