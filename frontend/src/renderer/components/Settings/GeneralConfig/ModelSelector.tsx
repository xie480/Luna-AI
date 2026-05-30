/**
 * 模型选择器组件
 * 做什么：提供 LLM 模型切换功能，包括模型名称、Base URL、Max Tokens、Temperature 等参数配置。
 * 为什么这样做：让用户可以在多个模型之间切换，支持本地 vLLM/Ollama 与云端 API 切换。
 */
import React, { useState, useCallback, useEffect } from 'react';
import { useConfigStore } from '../../../stores/configStore';

/** 预设模型列表 */
const PRESET_MODELS = [
  { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'GPT-4o-mini', value: 'gpt-4o-mini' },
  { label: 'Claude 3.5 Sonnet', value: 'claude-3-5-sonnet-20241022' },
  { label: 'Qwen2.5 (本地)', value: 'qwen2.5' },
  { label: 'DeepSeek V3', value: 'deepseek-chat' },
];

export const ModelSelector: React.FC = () => {
  const { config, updateConfig, error } = useConfigStore();
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // 当前模型配置状态（本地编辑）
  const [model, setModel] = useState(config?.llm_model || '');
  const [baseUrl, setBaseUrl] = useState(config?.llm_base_url || '');
  const [maxTokens, setMaxTokens] = useState(config?.llm_max_tokens ?? 4096);
  const [temperature, setTemperature] = useState(config?.llm_temperature ?? 0.7);

  // 当 config 发生外部更新（如 WS 推送）时，同步本地状态
  useEffect(() => {
    if (config) {
      setModel(config.llm_model || '');
      setBaseUrl(config.llm_base_url || '');
      setMaxTokens(config.llm_max_tokens ?? 4096);
      setTemperature(config.llm_temperature ?? 0.7);
    }
  }, [config]);

  /**
   * 保存模型配置
   */
  const handleSave = useCallback(async () => {
    // 输入校验
    if (!model.trim()) {
      setSaveError('模型名称不能为空');
      return;
    }
    if (maxTokens < 1 || maxTokens > 128000) {
      setSaveError('Max Tokens 必须在 1 ~ 128000 之间');
      return;
    }
    if (temperature < 0 || temperature > 2) {
      setSaveError('Temperature 必须在 0 ~ 2 之间');
      return;
    }

    setIsSaving(true);
    setSaveError(null);
    try {
      await updateConfig({
        llm_model: model.trim(),
        llm_base_url: baseUrl.trim() || undefined,
        llm_max_tokens: maxTokens,
        llm_temperature: temperature,
      });
    } catch (err: any) {
      setSaveError(err.message || '保存模型配置失败');
    } finally {
      setIsSaving(false);
    }
  }, [model, baseUrl, maxTokens, temperature, updateConfig]);

  /**
   * 选择预设模型
   */
  const handlePresetSelect = useCallback((presetValue: string) => {
    setModel(presetValue);
  }, []);

  return (
    <div className="model-selector">
      <label className="config-label">LLM 模型配置</label>
      <div className="config-control">
        {/* 预设模型快捷选择 */}
        <div className="preset-models">
          <span className="preset-label">快捷选择：</span>
          {PRESET_MODELS.map((pm) => (
            <button
              key={pm.value}
              className={`preset-btn ${model === pm.value ? 'active' : ''}`}
              onClick={() => handlePresetSelect(pm.value)}
              disabled={isSaving}
            >
              {pm.label}
            </button>
          ))}
        </div>

        {/* 模型名称 */}
        <div className="config-field">
          <label className="field-label">模型名称</label>
          <input
            className="config-input"
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="gpt-4o"
            disabled={isSaving}
          />
        </div>

        {/* API Base URL */}
        <div className="config-field">
          <label className="field-label">API Base URL（可选）</label>
          <input
            className="config-input"
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
            disabled={isSaving}
          />
        </div>

        {/* Max Tokens */}
        <div className="config-field">
          <label className="field-label">Max Tokens</label>
          <input
            className="config-input"
            type="number"
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
            min={1}
            max={128000}
            disabled={isSaving}
          />
        </div>

        {/* Temperature */}
        <div className="config-field">
          <label className="field-label">Temperature</label>
          <input
            className="config-input"
            type="number"
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            min={0}
            max={2}
            step={0.1}
            disabled={isSaving}
          />
        </div>

        <button
          className="config-btn config-btn-primary"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? '保存中...' : '保存模型配置'}
        </button>
        {saveError && <div className="config-error">{saveError}</div>}
        {error && !saveError && <div className="config-error">{error}</div>}
      </div>
    </div>
  );
};
