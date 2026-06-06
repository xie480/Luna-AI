import React, { useState } from 'react';
import {
  StrategySelector,
  SlidingWindowForm,
  StructuredStrategyForm,
  SemanticStrategyForm,
  RegexStrategyForm,
  ChunkPreviewSandbox
} from './StrategyConfig/StrategyConfig';
import { FileUploadDropzone, UrlScrapeInput, IngestionProgress } from './Ingestion/Ingestion';
import { KnowledgeFilter, KnowledgeTable } from './KnowledgeList/KnowledgeList';
import { useRagConfigStore } from '../../stores/ragConfigStore';
import './KnowledgeBasePanel.css';

export const KnowledgeBasePanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'ingestion' | 'list' | 'strategy'>('list');
  const { activeChunkStrategy } = useRagConfigStore();

  const renderStrategyForm = () => {
    switch (activeChunkStrategy) {
      case 'sliding_window':
        return <SlidingWindowForm />;
      case 'structured_ast':
        return (
          <>
            <SlidingWindowForm />
            <StructuredStrategyForm />
          </>
        );
      case 'semantic_parent_child':
        return (
          <>
            <SlidingWindowForm />
            <SemanticStrategyForm />
          </>
        );
      case 'regex':
        return (
          <>
            <SlidingWindowForm />
            <RegexStrategyForm />
          </>
        );
      default:
        return null;
    }
  };

  return (
    <div className="knowledge-base-panel">
      <div className="settings-sidebar">
        <div 
          className={`settings-nav-item ${activeTab === 'list' ? 'active' : ''}`}
          onClick={() => setActiveTab('list')}
        >
          <span className="nav-icon">📚</span>
          <span className="nav-text">知识库管理</span>
        </div>
        <div 
          className={`settings-nav-item ${activeTab === 'ingestion' ? 'active' : ''}`}
          onClick={() => setActiveTab('ingestion')}
        >
          <span className="nav-icon">📥</span>
          <span className="nav-text">添加知识</span>
        </div>
        <div 
          className={`settings-nav-item ${activeTab === 'strategy' ? 'active' : ''}`}
          onClick={() => setActiveTab('strategy')}
        >
          <span className="nav-icon">⚙️</span>
          <span className="nav-text">切片策略配置</span>
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
            <h3 className="settings-section-title">添加知识 (使用当前切片策略)</h3>
            <FileUploadDropzone />
            <UrlScrapeInput />
            <IngestionProgress />
          </div>
        )}

        {activeTab === 'strategy' && (
          <div className="settings-content-section">
            <h3 className="settings-section-title">切片策略沙盒</h3>
            <div className="strategy-config-area">
              <StrategySelector />
              {renderStrategyForm()}
            </div>
            <ChunkPreviewSandbox />
          </div>
        )}
      </div>
    </div>
  );
};
