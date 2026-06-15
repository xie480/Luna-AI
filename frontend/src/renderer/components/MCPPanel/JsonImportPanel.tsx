import React, { useState, useRef, useCallback } from 'react';
import type { LocalServerConfig } from '../../../shared/types';
import { useLocalServerStore } from '../../stores/mcpLocalServerStore';
import { parseLocalServerJSON, ImportResultSummary } from './jsonParser';

type ImportStage = 'input' | 'preview' | 'result';

export const JsonImportPanel: React.FC = () => {
  const [jsonText, setJsonText] = useState<string>('');
  const [parsedRows, setParsedRows] = useState<LocalServerConfig[]>([]);
  const [summary, setSummary] = useState<ImportResultSummary | null>(null);
  const [stage, setStage] = useState<ImportStage>('input');
  const [parseError, setParseError] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { batchRegisterServers, importStatus, importResult, resetImportStatus } =
    useLocalServerStore();

  /**
   * 解析 JSON 文本。
   */
  const handleParse = useCallback(() => {
    setParseError('');
    try {
      const result = parseLocalServerJSON(jsonText);
      setParsedRows(result.rows);
      setSummary(result.summary);
      setStage('preview');
    } catch (error) {
      setParseError(
        error instanceof Error ? error.message : 'JSON 解析失败'
      );
    }
  }, [jsonText]);

  /**
   * 处理文件上传。
   */
  const handleFileUpload = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target?.result as string;
        setJsonText(text);
        // 自动解析
        try {
          const result = parseLocalServerJSON(text);
          setParsedRows(result.rows);
          setSummary(result.summary);
          setStage('preview');
          setParseError('');
        } catch (error) {
          setJsonText(text);
          setParseError(
            error instanceof Error ? error.message : 'JSON 解析失败'
          );
          setStage('input');
        }
      };
      reader.onerror = () => {
        setParseError('文件读取失败');
      };
      reader.readAsText(file);
    },
    []
  );

  /**
   * 确认导入。
   */
  const handleConfirmImport = useCallback(async () => {
    resetImportStatus();
    try {
      await batchRegisterServers(parsedRows);
      setStage('result');
    } catch {
      // 错误已在 Store 中处理
    }
  }, [parsedRows, batchRegisterServers, resetImportStatus]);

  /**
   * 重置到输入阶段。
   */
  const handleReset = useCallback(() => {
    setJsonText('');
    setParsedRows([]);
    setSummary(null);
    setStage('input');
    setParseError('');
    resetImportStatus();
  }, [resetImportStatus]);

  /**
   * 格式化示例 JSON。
   */
  const exampleJSON = JSON.stringify(
    {
      servers: [
        {
          name: 'example-server',
          command: 'npx',
          args: ['-y', '@modelcontextprotocol/example'],
          env: { API_KEY: 'your-key' },
          description: '示例 MCP 服务器',
        },
      ],
    },
    null,
    2
  );

  // ===== 阶段一：输入 JSON =====
  if (stage === 'input') {
    return (
      <div className="json-import-panel">
        <div className="json-import-panel__file-upload">
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            style={{ display: 'none' }}
            onChange={handleFileUpload}
          />
          <button onClick={() => fileInputRef.current?.click()}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{verticalAlign: 'middle', marginRight: 6}}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="12" y1="18" x2="12" y2="12"/>
              <line x1="9" y1="15" x2="15" y2="15"/>
            </svg>
            选择 JSON 文件
          </button>
          <span className="hint-text">支持 .json 格式</span>
        </div>

        <div className="json-import-panel__editor">
          <textarea
            placeholder={`粘贴 JSON 配置到这里...\n\n示例格式：\n${exampleJSON}`}
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            rows={12}
          />
        </div>

        {parseError && (
          <div className="parse-error">{parseError}</div>
        )}

        <div className="json-import-panel__actions">
          <button
            className="btn-parse"
            onClick={handleParse}
            disabled={!jsonText.trim()}
          >
            解析并预览
          </button>
          <button className="btn-reset" onClick={handleReset}>
            重置
          </button>
        </div>
      </div>
    );
  }

  // ===== 阶段二：解析预览 =====
  if (stage === 'preview' && summary) {
    return (
      <div className="json-import-panel">
        <h4>解析预览（共 {summary.total} 条）</h4>

        <div className="import-preview-list">
          {summary.invalidItems.length > 0 && (
            <div className="import-preview__warnings">
              <strong>以下条目校验失败，将被跳过：</strong>
              {summary.invalidItems.map((item) => (
                <div key={item.index} className="import-preview__warning-item">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="#f59e0b" stroke="none" style={{verticalAlign: 'middle', marginRight: 4}}>
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                  </svg>
                  {item.name}: {Object.values(item.errors).join('; ')}
                </div>
              ))}
            </div>
          )}

          <div className="import-preview__valid-count">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#a082ff" stroke="none" style={{verticalAlign: 'middle', marginRight: 4}}>
              <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
            </svg>
            {summary.valid} 条有效配置待导入
          </div>
        </div>

        <div className="json-import-panel__actions">
          <button
            className="btn-confirm-import"
            onClick={handleConfirmImport}
            disabled={importStatus === 'importing' || parsedRows.length === 0}
          >
            {importStatus === 'importing' ? '导入中...' :
             `确认导入（${parsedRows.length} 条）`}
          </button>
          <button className="btn-back" onClick={() => setStage('input')}>
            返回修改
          </button>
        </div>

        {importStatus === 'error' && (
          <div className="submit-error">批量导入失败，请重试。</div>
        )}
      </div>
    );
  }

  // ===== 阶段三：导入结果 =====
  return (
    <div className="json-import-panel">
      <h4>批量导入完成</h4>
      <div className="import-result">
        <div className="import-result__success">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="#a082ff" stroke="none" style={{verticalAlign: 'middle', marginRight: 4}}>
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
          </svg>
          成功注册: {importResult?.success_count ?? 0} 条
        </div>
        <div className="import-result__failed">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="#e03e3e" stroke="none" style={{verticalAlign: 'middle', marginRight: 4}}>
            <path d="M18.3 5.71L12 12l6.3 6.29-1.42 1.42L12 13.41l-5.88 5.88-1.42-1.42L10.59 12 4.7 5.71 6.12 4.29 12 10.59l5.88-5.88 1.42 1.42z"/>
          </svg>
          失败: {importResult?.failed_count ?? 0} 条
        </div>
        {importResult?.failures && importResult.failures.length > 0 && (
          <div className="import-result__details">
            {importResult.failures.map((f, i) => (
              <div key={i} className="import-result__failure-item">
                {f.name}: {f.error}
              </div>
            ))}
          </div>
        )}
      </div>
      <button className="btn-reset" onClick={handleReset}>
        继续导入
      </button>
    </div>
  );
};
