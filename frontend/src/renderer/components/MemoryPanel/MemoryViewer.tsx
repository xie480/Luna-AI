import React, { useState, useEffect } from 'react';
import { memoryService, LongTermMemoryItem } from '../../services/memoryService';

export const MemoryViewer: React.FC = () => {
  const [memories, setMemories] = useState<LongTermMemoryItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize] = useState<number>(10);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [isFormOpen, setIsFormOpen] = useState<boolean>(false);
  const [formMode, setFormMode] = useState<'create' | 'edit'>('create');
  const [formData, setFormData] = useState<{ id?: string; session_id: string; summary: string }>({
    session_id: '',
    summary: ''
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const fetchMemories = async (currentPage: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await memoryService.getLongTermMemories(currentPage, pageSize);
      setMemories(data.items);
      setTotal(data.total);
      setPage(data.page);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || '获取长期记忆失败');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchMemories(page);
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = () => {
    fetchMemories(page);
  };

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= Math.ceil(total / pageSize)) {
      setPage(newPage);
    }
  };

  const openCreateForm = () => {
    setFormMode('create');
    setFormData({ session_id: '', summary: '' });
    setIsFormOpen(true);
  };

  const openEditForm = (memory: LongTermMemoryItem) => {
    setFormMode('edit');
    setFormData({ id: memory.id, session_id: memory.session_id, summary: memory.summary });
    setIsFormOpen(true);
  };

  const closeForm = () => {
    setIsFormOpen(false);
  };

  const handleFormSubmit = async () => {
    if (!formData.summary.trim()) {
      alert('摘要不能为空');
      return;
    }
    if (formMode === 'create' && !formData.session_id.trim()) {
      alert('会话 ID 不能为空');
      return;
    }

    setIsSubmitting(true);
    try {
      if (formMode === 'create') {
        await memoryService.createLongTermMemory(formData.session_id, formData.summary);
      } else if (formMode === 'edit' && formData.id) {
        await memoryService.updateLongTermMemory(formData.id, formData.summary);
      }
      closeForm();
      fetchMemories(page);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(`操作失败: ${message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('确定要删除这条长期记忆吗？此操作不可恢复。')) {
      try {
        await memoryService.deleteLongTermMemory(id);
        fetchMemories(page);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        alert(`删除失败: ${message}`);
      }
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="memory-viewer-container">
      <div className="viewer-toolbar">
        <button className="toolbar-btn primary" onClick={openCreateForm}>
          + 新增记忆
        </button>
        <button className="toolbar-btn" onClick={handleRefresh} disabled={isLoading}>
          {isLoading ? '刷新中...' : '刷新'}
        </button>
      </div>

      {error && <div style={{ color: 'var(--error-color)', marginBottom: '16px' }}>{error}</div>}

      <div className="memory-table-wrapper">
        <table className="memory-table">
          <thead>
            <tr>
              <th style={{ width: '15%' }}>记忆 ID</th>
              <th style={{ width: '15%' }}>会话 ID</th>
              <th style={{ width: '40%' }}>记忆摘要</th>
              <th style={{ width: '10%' }}>状态</th>
              <th style={{ width: '10%' }}>创建时间</th>
              <th style={{ width: '10%' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {memories.length > 0 ? (
              memories.map((memory) => (
                <tr key={memory.id}>
                  <td title={memory.id}>{memory.id.substring(0, 8)}...</td>
                  <td>{memory.session_id}</td>
                  <td className="summary-cell">{memory.summary}</td>
                  <td>{memory.status}</td>
                  <td>{memory.created_at ? new Date(memory.created_at).toLocaleDateString() : '-'}</td>
                  <td>
                    <div className="action-buttons">
                      <button className="action-btn" onClick={() => openEditForm(memory)} title="编辑">
                        ✏️
                      </button>
                      <button className="action-btn" onClick={() => handleDelete(memory.id)} title="删除">
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '32px' }}>
                  {isLoading ? '加载中...' : '暂无长期记忆数据'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="pagination">
          <button 
            className="toolbar-btn" 
            onClick={() => handlePageChange(page - 1)}
            disabled={page === 1 || isLoading}
          >
            上一页
          </button>
          <span className="page-info">
            第 {page} 页 / 共 {totalPages} 页 (总计 {total} 条)
          </span>
          <button 
            className="toolbar-btn" 
            onClick={() => handlePageChange(page + 1)}
            disabled={page === totalPages || isLoading}
          >
            下一页
          </button>
        </div>
      )}

      {/* Form Modal */}
      {isFormOpen && (
        <div className="memory-form-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeForm(); }}>
          <div className="memory-form-modal">
            <div className="memory-form-header">
              <h3>{formMode === 'create' ? '新增长期记忆' : '编辑长期记忆'}</h3>
              <button className="close-btn" onClick={closeForm}>✕</button>
            </div>
            <div className="memory-form-body">
              {formMode === 'create' && (
                <div className="form-group">
                  <label>会话 ID</label>
                  <input 
                    type="text" 
                    value={formData.session_id} 
                    onChange={(e) => setFormData({ ...formData, session_id: e.target.value })}
                    placeholder="例如: 20231001"
                  />
                </div>
              )}
              {formMode === 'edit' && (
                <div className="form-group">
                  <label>会话 ID</label>
                  <input type="text" value={formData.session_id} disabled style={{ opacity: 0.7 }} />
                </div>
              )}
              <div className="form-group">
                <label>记忆摘要</label>
                <textarea 
                  value={formData.summary} 
                  onChange={(e) => setFormData({ ...formData, summary: e.target.value })}
                  placeholder="输入记忆摘要内容..."
                />
              </div>
            </div>
            <div className="memory-form-footer">
              <button className="toolbar-btn" onClick={closeForm} disabled={isSubmitting}>取消</button>
              <button className="toolbar-btn primary" onClick={handleFormSubmit} disabled={isSubmitting}>
                {isSubmitting ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
