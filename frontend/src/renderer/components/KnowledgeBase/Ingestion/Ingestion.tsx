import React, { useState, useEffect } from 'react';
import { useKnowledgeStore } from '../../../stores/knowledgeStore';
import { useRagConfigStore } from '../../../stores/ragConfigStore';
import { createErrorToast } from '../../../stores/errorToastStore';
import {
  StrategySelector,
  SlidingWindowForm,
  StructuredStrategyForm,
  SemanticStrategyForm,
  RegexStrategyForm,
  ChunkPreviewSandbox
} from '../StrategyConfig/StrategyConfig';
import './Ingestion.css';

// Helper to read file as text
const readFileAsText = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target?.result as string || '');
    reader.onerror = (e) => reject(e);
    reader.readAsText(file);
  });
};

interface IngestionProps {
  isUpdateMode?: boolean;
  targetDocId?: string;
}

export const PendingItemsList: React.FC<IngestionProps> = ({ isUpdateMode }) => {
  const {
    pendingFiles, pendingUrls, removePendingFile, removePendingUrl,
    pendingFileDescriptions, pendingUrlDescriptions,
    setPendingFileDescription, setPendingUrlDescription,
  } = useKnowledgeStore();
  const { setPreviewSourceFile, setPreviewSourceUrl, setStrategyDebuggerOpen } = useRagConfigStore();
  
  if (pendingFiles.length === 0 && pendingUrls.length === 0) return null;

  const handlePreviewFile = (file: File) => {
    setPreviewSourceFile(file);
    setStrategyDebuggerOpen(true);
  };

  const handlePreviewUrl = (url: string) => {
    setPreviewSourceUrl(url);
    setStrategyDebuggerOpen(true);
  };

  return (
    <div className="pending-items-list">
      <h4 className="pending-title">{isUpdateMode ? '待更新列表（仅限单文件/网址）' : '\u5F85\u5904\u7406\u5217\u8868\uFF08\u5C1A\u672A\u5165\u5E93\uFF09'}</h4>
      <div className="pending-items-container">
        {pendingFiles.map((f, idx) => (
          <div key={`file-${idx}`} className="pending-item">
            <div className="pending-item-header">
              <span className="pending-icon text-blue">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                  <polyline points="10 9 9 9 8 9"></polyline>
                </svg>
              </span>
              <span className="pending-name" title={f.name}>{f.name}</span>
              <span className="pending-size">({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
              <button className="btn-preview-pending" onClick={() => handlePreviewFile(f)} title="预览此文件分片">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
              </button>
              <button className="btn-remove-pending" onClick={() => removePendingFile(idx)} title="移除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            <input
              className="pending-description-input"
              type="text"
              placeholder="输入文件简介（可选，最多 500 字符）"
              maxLength={500}
              value={pendingFileDescriptions[f.name] || ''}
              onChange={(e) => setPendingFileDescription(f.name, e.target.value)}
            />
          </div>
        ))}
        {pendingUrls.map((u, idx) => (
          <div key={`url-${idx}`} className="pending-item">
            <div className="pending-item-header">
              <span className="pending-icon text-green">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                </svg>
              </span>
              <span className="pending-name" title={u}>{u}</span>
              <button className="btn-preview-pending" onClick={() => handlePreviewUrl(u)} title="预览此网页分片">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
              </button>
              <button className="btn-remove-pending" onClick={() => removePendingUrl(idx)} title="移除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            <input
              className="pending-description-input"
              type="text"
              placeholder="输入网址简介（可选，最多 500 字符）"
              maxLength={500}
              value={pendingUrlDescriptions[u] || ''}
              onChange={(e) => setPendingUrlDescription(u, e.target.value)}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export const FileUploadDropzone: React.FC<IngestionProps> = ({ isUpdateMode }) => {
  const [isDragActive, setIsDragActive] = useState(false);
  const { addPendingFile, pendingFiles, pendingUrls } = useKnowledgeStore();
  const { setPreviewSourceFile, setStrategyDebuggerOpen } = useRagConfigStore();

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const handleFiles = async (files: File[]) => {
    if (isUpdateMode && files.length > 1) {
      createErrorToast('WARN', 'FileUpload', '更新模式下只能选择一个文件');
      return;
    }
    if (isUpdateMode && (pendingFiles.length > 0 || pendingUrls.length > 0)) {
      createErrorToast('WARN', 'FileUpload', '更新模式下只能保留一个待处理项，请先移除现有项');
      return;
    }

    for (const file of files) {
      try {
        addPendingFile(file);
        setPreviewSourceFile(file);
        useRagConfigStore.getState().fetchPreviewChunks();
        setStrategyDebuggerOpen(true);
        if (isUpdateMode) break; // 仅处理第一个文件
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        createErrorToast('WARN', 'FileUpload', `文件 [${file.name}] 拦截: ${message}`);
      }
    }
  };

  return (
    <div
      className={`file-upload-dropzone ${isDragActive ? 'active' : ''}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <input
        type="file"
        multiple
        onChange={handleFileSelect}
        style={{ display: 'none' }}
        id="file-upload-input"
      />
      <label htmlFor="file-upload-input" className="dropzone-label">
        <div className="dropzone-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="17 8 12 3 7 8"></polyline>
            <line x1="12" y1="3" x2="12" y2="15"></line>
          </svg>
        </div>
        <div className="dropzone-text">点击或拖拽文件到此处上传</div>
        <div className="dropzone-hint">支持 txt, md, pdf, docx (最大 50MB)</div>
      </label>
    </div>
  );
};

export const UrlScrapeInput: React.FC<IngestionProps> = ({ isUpdateMode }) => {
  const [url, setUrl] = useState('');
  const { addPendingUrl, pendingFiles, pendingUrls } = useKnowledgeStore();
  const { setPreviewSourceText, setStrategyDebuggerOpen } = useRagConfigStore();

  const handleAdd = () => {
    const trimmed = url.trim();
    if (!trimmed) return;

    if (isUpdateMode && (pendingFiles.length > 0 || pendingUrls.length > 0)) {
      createErrorToast('WARN', 'UrlScrape', '更新模式下只能保留一个待处理项，请先移除现有项');
      return;
    }
    
    try {
      addPendingUrl(trimmed);
      setUrl('');
      setPreviewSourceText(`(待入库网址: ${trimmed})\n此部分文本由于跨域无法在前端直接展示，但当您点击最下方【确认开始入库】后，后端将使用您下方配置的策略自动处理它。`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      createErrorToast('WARN', 'UrlScrape', `网址拦截: ${message}`);
    }
  };

  return (
    <div className="url-scrape-input">
      <input
        type="text"
        className="text-input"
        placeholder="输入网址并回车 (如 https://example.com)"
        value={url}
        onChange={e => setUrl(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') handleAdd();
        }}
      />
      <button
        className="btn-confirm"
        onClick={handleAdd}
        disabled={!url.trim()}
      >
        解析暂存
      </button>
    </div>
  );
};

export const IngestionProgress: React.FC = () => {
  const getProgressSnapshot = useKnowledgeStore(state => state.getProgressSnapshot);
  const snapshot = getProgressSnapshot();
  
  if (snapshot.activeCount === 0 && snapshot.completedCount === 0 && snapshot.failedCount === 0) {
    return null; // 不展示进度
  }

  return (
    <div className="ingestion-progress">
      <div className="progress-stats">
        <span>已完成: {snapshot.completedCount}</span>
        <span>处理中: {snapshot.activeCount}</span>
        {snapshot.failedCount > 0 && <span className="text-red">失败: {snapshot.failedCount}</span>}
      </div>
      <div className="progress-bar-container">
        <div 
          className="progress-bar-fill" 
          style={{ width: `${snapshot.globalPercent}%` }}
        />
      </div>
    </div>
  );
};

export const StrategyDebugger: React.FC<{ disabled?: boolean }> = ({ disabled }) => {
  const {
    activeChunkStrategy,
    fetchPreviewChunks,
    clearPreview,
    isStrategyDebuggerOpen,
    setStrategyDebuggerOpen,
    previewSourceType,
    previewSourceText,
    previewSourceFile,
    previewSourceUrl
  } = useRagConfigStore();

  const renderStrategyForm = () => {
    switch (activeChunkStrategy) {
      case 'sliding_window':
        return <SlidingWindowForm />;
      case 'structured_ast':
        return <StructuredStrategyForm />;
      case 'semantic_parent_child':
        return <SemanticStrategyForm />;
      case 'regex':
        return <RegexStrategyForm />;
      default:
        return null;
    }
  };

  // 监听策略或源文本变化，如果已展开策略面板且有文本，自动刷新预览
  // 注意：要让 useEffect 正确捕捉状态变化，必须把 store 中会改变的内容显式解构出来，或者把相关状态放到依赖数组。
  const slidingParams = useRagConfigStore(state => state.slidingParams);
  const structuredParams = useRagConfigStore(state => state.structuredParams);
  const semanticParams = useRagConfigStore(state => state.semanticParams);
  const regexParams = useRagConfigStore(state => state.regexParams);

  useEffect(() => {
    if (isStrategyDebuggerOpen && previewSourceType) {
      const timer = setTimeout(() => {
        fetchPreviewChunks();
      }, 500); // 防抖
      return () => clearTimeout(timer);
    }
  }, [
    isStrategyDebuggerOpen,
    previewSourceType,
    previewSourceText,
    previewSourceFile,
    previewSourceUrl,
    activeChunkStrategy,
    slidingParams,
    structuredParams,
    semanticParams,
    regexParams,
    fetchPreviewChunks
  ]);

  return (
    <div className="strategy-debugger-container">
      <div className="strategy-toggle-area">
        <button
          className="btn-strategy-toggle"
          onClick={() => {
            if (!disabled) {
              setStrategyDebuggerOpen(!isStrategyDebuggerOpen);
            }
          }}
          disabled={disabled}
        >
          <span className="toggle-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: isStrategyDebuggerOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </span>
          {disabled ? '更新模式下将自动继承原文档切片策略' : (isStrategyDebuggerOpen ? '收起切片策略' : '高级切片策略与调试')}
        </button>
      </div>

      {isStrategyDebuggerOpen && !disabled && (
        <div className="strategy-config-expanded">
          <div className="strategy-config-area">
            <StrategySelector />
            {renderStrategyForm()}
          </div>
          
          <div className="chunk-preview-sandbox">
            {previewSourceText ? (
              <div className="preview-source-info">
                ✓ 已获取最近一次录入的内容用于预览测试
              </div>
            ) : (
              <div className="preview-source-info text-muted">
                请先通过上方上传文件或提交网址，系统将自动提取内容进行策略预览。
              </div>
            )}
            <ChunkPreviewSandbox hideInput={true} />
          </div>
        </div>
      )}
    </div>
  );
};

export const GlobalSubmitButton: React.FC<IngestionProps> = ({ isUpdateMode, targetDocId }) => {
  const { pendingFiles, pendingUrls, submitAllPending, updateKnowledge, clearPendingQueue, setDocumentToUpdate } = useKnowledgeStore();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const totalPending = pendingFiles.length + pendingUrls.length;

  const handleGlobalSubmit = async () => {
    if (totalPending === 0) return;
    
    setIsSubmitting(true);
    try {
      if (isUpdateMode && targetDocId) {
        if (pendingFiles.length === 1) {
          await updateKnowledge(targetDocId, pendingFiles[0]);
          createErrorToast('SUCCESS', 'Success', '成功提交文档更新任务');
          clearPendingQueue();
          setDocumentToUpdate(null); // 返回列表视图
        } else if (pendingUrls.length === 1) {
          createErrorToast('WARN', 'Ingestion', '更新 URL 功能暂未实现');
        }
      } else {
        await submitAllPending();
        createErrorToast('SUCCESS', 'Success', `成功提交 ${totalPending} 项待处理数据进入知识库`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '部分或全部数据入库失败，请查看控制台';
      createErrorToast('ERROR', 'Ingestion', errMsg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="global-submit-container">
      {isSubmitting && (
        <div className="global-submit-progress">
          <div className="global-submit-progress-bar">
            <div className="global-submit-progress-fill"></div>
          </div>
          <div className="global-submit-progress-text">正在处理入库任务，请稍候...</div>
        </div>
      )}
      <button
        className="btn-global-submit"
        onClick={handleGlobalSubmit}
        disabled={totalPending === 0 || isSubmitting}
      >
        {isSubmitting ? '正在提交入库中...' : (isUpdateMode ? `确认更新文档` : `确认开始入库 (${totalPending} 项)`)}
      </button>
      {totalPending > 0 && !isSubmitting && (
        <div className="global-submit-hint text-muted">
          注意：将使用上方配置的【最新切片策略】统一处理{isUpdateMode ? '该内容' : '所有暂存内容'}
        </div>
      )}
    </div>
  );
};
