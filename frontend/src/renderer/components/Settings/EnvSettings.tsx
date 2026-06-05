import React, { useState, useEffect, useCallback } from 'react';

export const EnvSettings: React.FC = () => {
  const [originalContent, setOriginalContent] = useState('');
  const [currentContent, setCurrentContent] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isModified = originalContent !== currentContent;

  const loadEnvFile = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const content = await window.electronAPI.readEnvFile();
      setOriginalContent(content);
      setCurrentContent(content);
    } catch (err) {
      console.error('Failed to read .env file:', err);
      setError('读取 .env 文件失败，请检查文件是否存在或权限是否正确。');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEnvFile();
  }, [loadEnvFile]);

  const handleReset = () => {
    setCurrentContent(originalContent);
  };

  const handleSaveClick = () => {
    setShowConfirmDialog(true);
  };

  const handleConfirmSave = async () => {
    try {
      const success = await window.electronAPI.writeEnvFile(currentContent);
      if (success) {
        await window.electronAPI.restartApp();
      } else {
        setError('保存失败，请重试。');
        setShowConfirmDialog(false);
      }
    } catch (err) {
      console.error('Failed to write .env file:', err);
      setError('保存 .env 文件失败，请检查权限。');
      setShowConfirmDialog(false);
    }
  };

  const handleCancelSave = () => {
    setShowConfirmDialog(false);
  };

  if (isLoading) {
    return <div className="env-settings-loading">正在加载环境配置...</div>;
  }

  return (
    <div className="settings-content-section env-settings-section">
      <div className="env-settings-header">
        <div className="env-settings-title-group">
          <h3 className="settings-section-title">环境配置 (.env)</h3>
          <span className="env-settings-desc">修改本地环境变量。保存后将自动重启软件以使配置生效。</span>
        </div>
        {isModified && (
          <div className="env-settings-actions">
            <button className="btn-reset" onClick={handleReset}>重置</button>
            <button className="btn-save" onClick={handleSaveClick}>保存并重启</button>
          </div>
        )}
      </div>

      {error && <div className="env-settings-error">{error}</div>}

      <div className="env-editor-container">
        <textarea
          className="env-editor-textarea"
          value={currentContent}
          onChange={(e) => setCurrentContent(e.target.value)}
          spellCheck={false}
        />
      </div>

      {/* 自定义确认弹窗 */}
      {showConfirmDialog && (
        <div className="env-confirm-overlay">
          <div className="env-confirm-dialog">
            <h4>确认保存并重启？</h4>
            <p>保存环境配置后，软件将立即自动重启以应用新的设置。请确保您已保存其他工作。</p>
            <div className="env-confirm-actions">
              <button className="btn-cancel" onClick={handleCancelSave}>取消</button>
              <button className="btn-confirm" onClick={handleConfirmSave}>确认重启</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
