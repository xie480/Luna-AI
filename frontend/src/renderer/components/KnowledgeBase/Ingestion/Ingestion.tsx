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

export const PendingItemsList: React.FC = () => {
  const { pendingFiles, pendingUrls, removePendingFile, removePendingUrl } = useKnowledgeStore();
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
      <h4 className="pending-title">待处理列表（尚未入库）</h4>
      <div className="pending-items-container">
        {pendingFiles.map((f, idx) => (
          <div key={`file-${idx}`} className="pending-item">
            <span className="pending-icon text-blue">📄</span>
            <span className="pending-name" title={f.name}>{f.name}</span>
            <span className="pending-size">({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
            <button className="btn-preview-pending" onClick={() => handlePreviewFile(f)} title="预览此文件分片">👁</button>
            <button className="btn-remove-pending" onClick={() => removePendingFile(idx)} title="移除">✕</button>
          </div>
        ))}
        {pendingUrls.map((u, idx) => (
          <div key={`url-${idx}`} className="pending-item">
            <span className="pending-icon text-green">🔗</span>
            <span className="pending-name" title={u}>{u}</span>
            <button className="btn-preview-pending" onClick={() => handlePreviewUrl(u)} title="预览此网页分片">👁</button>
            <button className="btn-remove-pending" onClick={() => removePendingUrl(idx)} title="移除">✕</button>
          </div>
        ))}
      </div>
    </div>
  );
};

export const FileUploadDropzone: React.FC = () => {
  const [isDragActive, setIsDragActive] = useState(false);
  const addPendingFile = useKnowledgeStore(state => state.addPendingFile);
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
    for (const file of files) {
      try {
        addPendingFile(file);
        // File is successfully validated and added, now let's set it to be previewed
        setPreviewSourceFile(file);
        useRagConfigStore.getState().fetchPreviewChunks();
        setStrategyDebuggerOpen(true);
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

export const UrlScrapeInput: React.FC = () => {
  const [url, setUrl] = useState('');
  const addPendingUrl = useKnowledgeStore(state => state.addPendingUrl);
  const { setPreviewSourceText, setStrategyDebuggerOpen } = useRagConfigStore();

  const handleAdd = () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    
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

export const StrategyDebugger: React.FC = () => {
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
            setStrategyDebuggerOpen(!isStrategyDebuggerOpen);
          }}
        >
          <span className="toggle-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: isStrategyDebuggerOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </span>
          {isStrategyDebuggerOpen ? '收起切片策略' : '高级切片策略与调试'}
        </button>
      </div>

      {isStrategyDebuggerOpen && (
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

export const GlobalSubmitButton: React.FC = () => {
  const { pendingFiles, pendingUrls, submitAllPending } = useKnowledgeStore();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const totalPending = pendingFiles.length + pendingUrls.length;

  const handleGlobalSubmit = async () => {
    if (totalPending === 0) return;
    
    setIsSubmitting(true);
    try {
      await submitAllPending();
      createErrorToast('ERROR', 'Success', `成功提交 ${totalPending} 项待处理数据进入知识库`);
    } catch (err: unknown) {
      // Error is already logged and thrown in submitAllPending, so we can just catch it here
      // createErrorToast will have been handled by the error boundary or we can show a generic one
      createErrorToast('ERROR', 'Ingestion', '部分或全部数据入库失败，请查看控制台');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="global-submit-container">
      <button
        className="btn-global-submit"
        onClick={handleGlobalSubmit}
        disabled={totalPending === 0 || isSubmitting}
      >
        {isSubmitting ? '正在提交入库中...' : `确认开始入库 (${totalPending} 项)`}
      </button>
      {totalPending > 0 && (
        <div className="global-submit-hint text-muted">
          注意：将使用上方配置的【最新切片策略】统一处理所有暂存内容
        </div>
      )}
    </div>
  );
};
