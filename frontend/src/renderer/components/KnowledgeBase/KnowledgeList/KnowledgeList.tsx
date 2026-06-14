import React, { useEffect, useRef, useState } from 'react';
import { useKnowledgeStore } from '../../../stores/knowledgeStore';
import { KnowledgeDocumentView } from '../../../types/rag';
import { createErrorToast } from '../../../stores/errorToastStore';
import './KnowledgeList.css';

export const KnowledgeFilter: React.FC<{ forceStatus?: string }> = ({ forceStatus }) => {
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
      
      {!forceStatus && (
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
      )}
    </div>
  );
};

const KnowledgeItemRow: React.FC<{ doc: KnowledgeDocumentView; isUpdateSelectorMode?: boolean }> = ({ doc, isUpdateSelectorMode }) => {
  const deleteKnowledge = useKnowledgeStore(state => state.deleteKnowledge);
  const updateKnowledge = useKnowledgeStore(state => state.updateKnowledge);
  const updatingDocIds = useKnowledgeStore(state => state.updatingDocIds);
  const setDocumentToUpdate = useKnowledgeStore(state => state.setDocumentToUpdate);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const isThisUpdating = updatingDocIds.has(doc.id);

  /** 点击更新按钮跳转至更新面板 */
  const handleUpdateClick = () => {
    setDocumentToUpdate(doc);
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteKnowledge(doc.id);
      if (updateKnowledge && isThisUpdating) {
        // dummy check to avoid typescript unused warning
      }
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
          <span className="flex items-center gap-1">
            {doc.source_type === 'local_file' ? (
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
            {doc.source_type === 'local_file' ? '文件' : '网页'}
          </span>
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
        {doc.description && (
          <div className="doc-description">{doc.description}</div>
        )}
        {doc.error_log && (
          <div className="doc-error" title={doc.error_log}>
            错误: {doc.error_log}
          </div>
        )}
      </div>
      
      <div className="doc-actions">
        {isUpdateSelectorMode ? (
          <button
            className="btn-action"
            onClick={handleUpdateClick}
          >
            更新此文档
          </button>
        ) : showConfirm ? (
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
          <>
            <button
              className="btn-action btn-icon"
              onClick={() => setShowConfirm(true)}
              title="删除"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                <line x1="10" y1="11" x2="10" y2="17"></line>
                <line x1="14" y1="11" x2="14" y2="17"></line>
              </svg>
            </button>
          </>
        )}
      </div>
    </div>
  );
};
export const KnowledgeTable: React.FC<{ isUpdateSelectorMode?: boolean }> = ({ isUpdateSelectorMode }) => {
  const documents = useKnowledgeStore(state => state.documents);
  const filterState = useKnowledgeStore(state => state.filterState);
  const fetchKnowledgeList = useKnowledgeStore(state => state.fetchKnowledgeList);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    fetchKnowledgeList().finally(() => setIsLoading(false));
  }, [fetchKnowledgeList]);

  const docs = React.useMemo(() => {
    return documents.filter(doc => {
      if (isUpdateSelectorMode && doc.status !== 'completed' && doc.status !== 'active') return false;
      if (filterState.sourceType !== 'all' && doc.source_type !== filterState.sourceType) return false;
      if (!isUpdateSelectorMode && filterState.status !== 'all' && doc.display_status !== filterState.status) return false;
      if (filterState.keyword && !doc.filename.toLowerCase().includes(filterState.keyword.toLowerCase())) return false;
      return true;
    });
  }, [documents, filterState, isUpdateSelectorMode]);

  if (isLoading) {
    return <div className="knowledge-loading">加载知识库...</div>;
  }

  if (docs.length === 0) {
    return (
      <div className="knowledge-empty">
        <div className="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
          </svg>
        </div>
        <div>没有找到匹配的知识文档</div>
      </div>
    );
  }

  return (
    <div className="knowledge-table">
      {docs.map(doc => (
        <KnowledgeItemRow key={doc.id} doc={doc} isUpdateSelectorMode={isUpdateSelectorMode} />
      ))}
    </div>
  );
};
