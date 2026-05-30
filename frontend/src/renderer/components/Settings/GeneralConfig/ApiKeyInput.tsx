/**
 * API Key 安全输入组件
 * 做什么：提供安全的 API Key 输入面板，以密码框掩码输入，提交后立即清除组件内部的明文状态。
 * 为什么这样做：确保敏感信息在前端内存中生命周期最短，绝不落盘。后端仅返回是否已设置的布尔值。
 */
import React, { useState, useCallback } from 'react';
import { useConfigStore } from '../../../stores/configStore';

export const ApiKeyInput: React.FC = () => {
  const { config, updateConfig, error } = useConfigStore();
  const [isEditing, setIsEditing] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  /** 后端指示是否已设置 API Key（脱敏状态，前端不接触明文） */
  const isKeySet = config?.has_llm_api_key ?? false;

  /**
   * 保存 API Key
   * 提交后立即清除输入框中的明文状态
   */
  const handleSave = useCallback(async () => {
    // 输入校验：不允许空字符串
    if (!inputValue.trim()) {
      setSaveError('API Key 不能为空');
      return;
    }

    setIsSaving(true);
    setSaveError(null);
    try {
      // 对应后端 config_handler.go 中的 llm_api_key 字段
      await updateConfig({ llm_api_key: inputValue });
      // 提交后立即清除明文状态
      setInputValue('');
      setIsEditing(false);
    } catch (err: any) {
      setSaveError(err.message || '保存 API Key 失败');
    } finally {
      setIsSaving(false);
    }
  }, [inputValue, updateConfig]);

  /**
   * 取消编辑
   * 清除输入框中的明文状态
   */
  const handleCancel = useCallback(() => {
    setInputValue('');
    setSaveError(null);
    setIsEditing(false);
  }, []);

  return (
    <div className="api-key-input">
      <label className="config-label">LLM API Key</label>
      <div className="config-control">
        {isEditing ? (
          <div className="api-key-edit-group">
            <input
              className="config-input config-input-password"
              type="password"
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                setSaveError(null);
              }}
              placeholder="sk-..."
              autoFocus
              disabled={isSaving}
            />
            <div className="api-key-actions">
              <button
                className="config-btn config-btn-primary"
                onClick={handleSave}
                disabled={isSaving}
              >
                {isSaving ? '保存中...' : '保存'}
              </button>
              <button
                className="config-btn config-btn-secondary"
                onClick={handleCancel}
                disabled={isSaving}
              >
                取消
              </button>
            </div>
            {saveError && <div className="config-error">{saveError}</div>}
          </div>
        ) : (
          <div className="api-key-display-group">
            <span className={`api-key-status ${isKeySet ? 'key-set' : 'key-not-set'}`}>
              {isKeySet ? '已设置 (********)' : '未设置'}
            </span>
            <button
              className="config-btn config-btn-secondary"
              onClick={() => setIsEditing(true)}
            >
              {isKeySet ? '修改' : '设置'}
            </button>
          </div>
        )}
        {error && !saveError && <div className="config-error">{error}</div>}
      </div>
    </div>
  );
};
