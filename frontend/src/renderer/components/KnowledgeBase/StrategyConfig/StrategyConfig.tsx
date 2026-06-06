import React, { useState, useEffect } from 'react';
import { useRagConfigStore } from '../../../stores/ragConfigStore';
import { RagChunkStrategy } from '../../../types/rag';
import './StrategyConfig.css';

export const StrategySelector: React.FC = () => {
  const { activeChunkStrategy, setActiveStrategy } = useRagConfigStore();

  return (
    <div className="strategy-selector">
      <label>选择切片策略：</label>
      <select 
        value={activeChunkStrategy} 
        onChange={(e) => setActiveStrategy(e.target.value as RagChunkStrategy)}
        className="theme-select"
      >
        <option value="structured_ast">结构化 Markdown 解析 (推荐)</option>
        <option value="semantic_parent_child">语义级联 (小至大)</option>
        <option value="sliding_window">基础滑动窗口</option>
        <option value="regex">正则表达式</option>
      </select>
    </div>
  );
};

export const SlidingWindowForm: React.FC = () => {
  const { slidingParams, updateSlidingParams } = useRagConfigStore();
  
  return (
    <div className="strategy-form">
      <div className="form-group">
        <label>Chunk Size (预估 Token 数): {slidingParams.chunkSize}</label>
        <input 
          type="range" 
          min="100" max="2000" step="10" 
          value={slidingParams.chunkSize} 
          onChange={(e) => updateSlidingParams({ chunkSize: Number(e.target.value) })}
        />
      </div>
      <div className="form-group">
        <label>Overlap (重叠 Token 数): {slidingParams.chunkOverlap}</label>
        <input 
          type="range" 
          min="0" max={Math.floor(slidingParams.chunkSize / 2)} step="10" 
          value={slidingParams.chunkOverlap} 
          onChange={(e) => updateSlidingParams({ chunkOverlap: Number(e.target.value) })}
        />
      </div>
    </div>
  );
};

export const StructuredStrategyForm: React.FC = () => {
  const { structuredParams, updateStructuredParams } = useRagConfigStore();
  
  return (
    <div className="strategy-form">
      <div className="form-group row">
        <label>提取 Markdown Header 作为前缀</label>
        <label className="switch">
          <input 
            type="checkbox" 
            checked={structuredParams.includeMetadata} 
            onChange={(e) => updateStructuredParams({ includeMetadata: e.target.checked })}
          />
          <span className="slider round"></span>
        </label>
      </div>
      <div className="form-group row">
        <label>保护 Markdown 表格完整性</label>
        <label className="switch">
          <input 
            type="checkbox" 
            checked={structuredParams.keepTablesIntact} 
            onChange={(e) => updateStructuredParams({ keepTablesIntact: e.target.checked })}
          />
          <span className="slider round"></span>
        </label>
      </div>
    </div>
  );
};

export const SemanticStrategyForm: React.FC = () => {
  const { semanticParams, updateSemanticParams } = useRagConfigStore();
  
  return (
    <div className="strategy-form">
      <div className="form-group row">
        <label>开启父子级联召回优化 (Small-to-Big)</label>
        <label className="switch">
          <input 
            type="checkbox" 
            checked={semanticParams.enableParentChild} 
            onChange={(e) => updateSemanticParams({ enableParentChild: e.target.checked })}
          />
          <span className="slider round"></span>
        </label>
      </div>
    </div>
  );
};

export const RegexStrategyForm: React.FC = () => {
  const { regexParams, updateRegexParams } = useRagConfigStore();
  
  return (
    <div className="strategy-form">
      <div className="form-group">
        <label>提取正则 (Python `re` 语法)</label>
        <input 
          type="text" 
          value={regexParams.startRegex} 
          onChange={(e) => updateRegexParams({ startRegex: e.target.value })}
          placeholder="例如：(?s)<article>(.*?)</article>"
          className="text-input"
        />
      </div>
      <div className="form-group">
        <label>兜底截断阈值 (Max Tokens): {regexParams.maxTokenFallback}</label>
        <input 
          type="range" 
          min="200" max="3000" step="100" 
          value={regexParams.maxTokenFallback} 
          onChange={(e) => updateRegexParams({ maxTokenFallback: Number(e.target.value) })}
        />
      </div>
    </div>
  );
};

// Chunk Preview Sandbox
export const ChunkPreviewSandbox: React.FC = () => {
  const [testText, setTestText] = useState('');
  const { 
    fetchPreviewChunks, 
    clearPreview, 
    isPreviewLoading, 
    previewError, 
    previewResults, 
    previewTotalChunks,
    previewWarnings 
  } = useRagConfigStore();

  useEffect(() => {
    return () => clearPreview();
  }, [clearPreview]);

  const handlePreview = () => {
    if (!testText.trim()) return;
    fetchPreviewChunks(testText);
  };

  const getBorderColor = (tokens: number) => {
    if (tokens < 512) return 'border-green';
    if (tokens <= 1000) return 'border-orange';
    return 'border-red';
  };

  return (
    <div className="chunk-preview-sandbox">
      <div className="sandbox-input-area">
        <textarea 
          className="sandbox-textarea"
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          placeholder="在此粘贴测试文本进行切片预览..."
        />
        <div className="sandbox-actions">
          <button 
            className="btn-confirm" 
            onClick={handlePreview}
            disabled={isPreviewLoading || !testText.trim()}
          >
            {isPreviewLoading ? '处理中...' : '▶ 预览切片效果'}
          </button>
        </div>
      </div>
      
      {previewError && (
        <div className="sandbox-error">
          {previewError}
        </div>
      )}

      {previewWarnings.length > 0 && (
        <div className="sandbox-warnings">
          {previewWarnings.map((warn, idx) => (
            <div key={idx}>⚠️ {warn}</div>
          ))}
        </div>
      )}

      <div className="sandbox-results">
        {isPreviewLoading ? (
          <div className="skeleton-cards">
            <div className="skeleton-card" />
            <div className="skeleton-card" />
          </div>
        ) : (
          previewResults.length > 0 && (
            <>
              <div className="results-summary">
                显示前 {previewResults.length} 个 Chunk，共产生 {previewTotalChunks} 个 Chunk。
              </div>
              <div className="chunk-cards">
                {previewResults.map((chunk, idx) => (
                  <div key={chunk.chunk_id} className={`chunk-card ${getBorderColor(chunk.estimated_tokens)}`}>
                    <div className="chunk-header">
                      <span className="chunk-idx">Chunk #{idx + 1}</span>
                      <span className={`chunk-tokens ${chunk.estimated_tokens > 1000 ? 'text-red' : ''}`}>
                        {chunk.estimated_tokens} Tokens
                        {chunk.estimated_tokens > 1000 && ' ❗️'}
                      </span>
                    </div>
                    <div className="chunk-body font-mono">
                      {chunk.text}
                    </div>
                    {Object.keys(chunk.metadata).length > 0 && (
                      <div className="chunk-footer">
                        {JSON.stringify(chunk.metadata)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )
        )}
      </div>
    </div>
  );
};
