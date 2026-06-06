import React, { useState } from 'react';
import { useKnowledgeStore } from '../../../stores/knowledgeStore';
import { RAG_MAX_UPLOAD_BYTES } from '../../../types/rag';
import { createErrorToast } from '../../../stores/errorToastStore';
import './Ingestion.css';

export const FileUploadDropzone: React.FC = () => {
  const [isDragActive, setIsDragActive] = useState(false);
  const submitLocalFile = useKnowledgeStore(state => state.submitLocalFile);

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
      if (file.size > RAG_MAX_UPLOAD_BYTES) {
        createErrorToast('WARN', 'FileUpload', `文件 ${file.name} 超过 50MB 限制，请手动分割`);
        continue;
      }
      try {
        await submitLocalFile(file);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        createErrorToast('ERROR', 'FileUpload', `提交文件 ${file.name} 失败: ${message}`);
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
        <div className="dropzone-icon">📁</div>
        <div className="dropzone-text">点击或拖拽文件到此处上传</div>
        <div className="dropzone-hint">支持 txt, md, pdf, docx (最大 50MB)</div>
      </label>
    </div>
  );
};

export const UrlScrapeInput: React.FC = () => {
  const [url, setUrl] = useState('');
  const submitUrl = useKnowledgeStore(state => state.submitUrl);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      createErrorToast('WARN', 'UrlScrape', '请输入有效的 HTTP/HTTPS URL');
      return;
    }

    setIsSubmitting(true);
    try {
      await submitUrl(trimmed);
      setUrl('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      createErrorToast('ERROR', 'UrlScrape', `提交 URL 失败: ${message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="url-scrape-input">
      <input
        type="text"
        className="text-input"
        placeholder="输入网址 (如 https://example.com)"
        value={url}
        onChange={e => setUrl(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') handleSubmit();
        }}
      />
      <button 
        className="btn-confirm" 
        onClick={handleSubmit}
        disabled={isSubmitting || !url.trim()}
      >
        {isSubmitting ? '抓取中...' : '添加网址'}
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
