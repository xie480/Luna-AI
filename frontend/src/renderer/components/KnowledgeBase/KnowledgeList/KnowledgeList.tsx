import React, { useEffect, useState } from 'react';
import { useKnowledgeStore } from '../../../stores/knowledgeStore';
import { KnowledgeDocumentView } from '../../../types/rag';
import { createErrorToast } from '../../../stores/errorToastStore';
import './KnowledgeList.css';

export const KnowledgeFilter: React.FC = () => {
  const { filterState, setFilterState } = useKnowledgeStore();

  return (
    <div className="knowledge-filter">
      <input 
        type="text" 
        className="text-input filter-keyword" 
        placeholder="搜索文件名..."
        value={filterState.keyword}
        onChange={e => setFilterState({ keyword: e.target.value })}
      />
      
      <select
        className="theme-select filter-select"
        value={filterState.sourceType}
        onChange={e => setFilterState({ sourceType: e.target.value as KnowledgeFilterState['sourceType'] })}
      >
        <option value="all">所有来源</option>
        <option value="local_file">本地文件</option>
        <option value="url">URL</option>
      </select>
      
      <select
        className="theme-select filter-select"
        value={filterState.status}
        onChange={e => setFilterState({ status: e.target.value as KnowledgeFilterState['status'] })}
      >
        <option value="all">所有状态</option>
        <option value="completed">已完成</option>
        <option value="parsing">解析中</option>
        <option value="embedding">向量化中</option>
        <option value="failed">失败</option>
        <option value="offline_suspended">挂起 (离线)</option>
      </select>
    </div>
  );
};

const KnowledgeItemRow: React.FC<{ doc: KnowledgeDocumentView }> = ({ doc }) => {
  const deleteKnowledge = useKnowledgeStore(state => state.deleteKnowledge);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteKnowledge(doc.id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      createErrorToast('ERROR', 'DeleteKnowledge', `删除失败: ${message}`);
      setIsDeleting(false);
      setShowConfirm(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-green';
      case 'failed': return 'text-red';
      case 'offline_suspended': return 'text-gray';
      default: return 'text-orange'; // parsing, embedding
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed': return '已就绪';
      case 'parsing': return '解析中';
      case 'embedding': return '向量化中';
      case 'failed': return '失败';
      case 'offline_suspended': return '挂起 (离线)';
      default: return status;
    }
  };

  return (
    <div className={`knowledge-row ${showConfirm ? 'confirm-mode' : ''}`}>
      <div className="doc-info">
        <div className="doc-title" title={doc.filename}>{doc.filename}</div>
        <div className="doc-meta">
          <span>{doc.source_type === 'local_file' ? '📁 文件' : '🌐 网页'}</span>
          <span>·</span>
          <span>{doc.estimated_tokens > 0 ? `${doc.estimated_tokens} Tokens` : '计算中...'}</span>
          <span>·</span>
          <span className={getStatusColor(doc.display_status)}>
            {getStatusText(doc.display_status)}
          </span>
          {doc.created_at && (
            <>
              <span>·</span>
              <span>{new Date(doc.created_at).toLocaleString()}</span>
            </>
          )}
        </div>
        {doc.error_log && (
          <div className="doc-error" title={doc.error_log}>
            错误: {doc.error_log}
          </div>
        )}
      </div>
      
      <div className="doc-actions">
        {showConfirm ? (
          <div className="confirm-actions">
            <span className="confirm-text">确定删除？</span>
            <button 
              className="btn-action btn-danger" 
              onClick={handleDelete}
              disabled={isDeleting}
            >
              确定
            </button>
            <button 
              className="btn-action" 
              onClick={() => setShowConfirm(false)}
              disabled={isDeleting}
            >
              取消
            </button>
          </div>
        ) : (
          <button 
            className="btn-action btn-icon" 
            onClick={() => setShowConfirm(true)}
            title="删除"
          >
            🗑️
          </button>
        )}
      </div>
    </div>
  );
};

export const KnowledgeTable: React.FC = () => {
  const getFilteredDocuments = useKnowledgeStore(state => state.getFilteredDocuments);
  const fetchKnowledgeList = useKnowledgeStore(state => state.fetchKnowledgeList);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchKnowledgeList().finally(() => setIsLoading(false));
  }, [fetchKnowledgeList]);

  const docs = getFilteredDocuments();

  if (isLoading) {
    return <div className="knowledge-loading">加载知识库...</div>;
  }

  if (docs.length === 0) {
    return (
      <div className="knowledge-empty">
        <div className="empty-icon">📚</div>
        <div>没有找到匹配的知识文档</div>
      </div>
    );
  }

  return (
    <div className="knowledge-table">
      {docs.map(doc => (
        <KnowledgeItemRow key={doc.id} doc={doc} />
      ))}
    </div>
  );
};
