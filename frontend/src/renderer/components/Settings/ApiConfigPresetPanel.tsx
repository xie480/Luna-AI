import React, { useEffect, useState, useCallback } from 'react';
import { useApiConfigPresetStore } from '../../stores/apiConfigPresetStore';
import { ModelConfig } from '../../services/apiConfigPresetService';
import './ApiConfigPresetPanel.css';

const DEFAULT_MODEL_CONFIG: ModelConfig = {
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model_id: '',
  max_tokens: 8192,
  temperature: 0.7,
};

export const ApiConfigPresetPanel: React.FC = () => {
  const {
    presets,
    isLoading,
    error,
    fetchPresets,
    savePreset,
    activatePreset,
    fetchModels,
  } = useApiConfigPresetStore();

  const [selectedPresetId, setSelectedPresetId] = useState<string>('');
  const [largeConfig, setLargeConfig] = useState<ModelConfig>({ ...DEFAULT_MODEL_CONFIG });
  const [mediumConfig, setMediumConfig] = useState<ModelConfig>({ ...DEFAULT_MODEL_CONFIG });
  const [smallConfig, setSmallConfig] = useState<ModelConfig>({ ...DEFAULT_MODEL_CONFIG });

  const [largeModels, setLargeModels] = useState<{ id: string; name: string }[]>([]);
  const [mediumModels, setMediumModels] = useState<{ id: string; name: string }[]>([]);
  const [smallModels, setSmallModels] = useState<{ id: string; name: string }[]>([]);

  const [isFetchingLarge, setIsFetchingLarge] = useState(false);
  const [isFetchingMedium, setIsFetchingMedium] = useState(false);
  const [isFetchingSmall, setIsFetchingSmall] = useState(false);

  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  const handleSelectPreset = useCallback((id: string) => {
    setSelectedPresetId(id);
    const preset = presets.find(p => p.id === id);
    if (preset) {
      setLargeConfig(preset.large_model_config);
      setMediumConfig(preset.medium_model_config);
      setSmallConfig(preset.small_model_config);
      // 切换预设时清空模型列表，需要重新获取
      setLargeModels(preset.large_model_config.model_id ? [{ id: preset.large_model_config.model_id, name: preset.large_model_config.model_id }] : []);
      setMediumModels(preset.medium_model_config.model_id ? [{ id: preset.medium_model_config.model_id, name: preset.medium_model_config.model_id }] : []);
      setSmallModels(preset.small_model_config.model_id ? [{ id: preset.small_model_config.model_id, name: preset.small_model_config.model_id }] : []);
    }
  }, [presets]);

  useEffect(() => {
    if (presets.length > 0 && !selectedPresetId) {
      const active = presets.find(p => p.is_active) || presets[0];
      handleSelectPreset(active.id);
    }
  }, [presets, selectedPresetId, handleSelectPreset]);

  const handleNewPreset = () => {
    setSelectedPresetId('');
    setLargeConfig({ ...DEFAULT_MODEL_CONFIG });
    setMediumConfig({ ...DEFAULT_MODEL_CONFIG });
    setSmallConfig({ ...DEFAULT_MODEL_CONFIG });
    setLargeModels([]);
    setMediumModels([]);
    setSmallModels([]);
  };

  const handleSaveClick = () => {
    const currentPreset = presets.find(p => p.id === selectedPresetId);
    setNewPresetName(currentPreset ? currentPreset.name : '');
    setShowSaveDialog(true);
  };

  const handleConfirmSave = async () => {
    if (!newPresetName.trim()) return;
    try {
      const id = await savePreset({
        id: selectedPresetId,
        name: newPresetName.trim(),
        large_model_config: largeConfig,
        medium_model_config: mediumConfig,
        small_model_config: smallConfig,
      });
      await activatePreset(id);
      setSelectedPresetId(id);
      setShowSaveDialog(false);
    } catch (e) {
      // Error is handled by store
    }
  };

  const handleFetchModels = async (
    size: 'large' | 'medium' | 'small',
    config: ModelConfig,
    setModels: React.Dispatch<React.SetStateAction<{ id: string; name: string }[]>>,
    setIsFetching: React.Dispatch<React.SetStateAction<boolean>>
  ) => {
    if (!config.base_url) return;
    setIsFetching(true);
    try {
      const models = await fetchModels(config.base_url, config.api_key);
      setModels(models);
      // 如果当前选中的模型不在新列表中，清空选择
      if (config.model_id && !models.find(m => m.id === config.model_id)) {
        if (size === 'large') setLargeConfig({ ...config, model_id: '' });
        if (size === 'medium') setMediumConfig({ ...config, model_id: '' });
        if (size === 'small') setSmallConfig({ ...config, model_id: '' });
      }
    } catch (e) {
      // Error handled by store
    } finally {
      setIsFetching(false);
    }
  };

  const renderModelBlock = (
    title: string,
    size: 'large' | 'medium' | 'small',
    config: ModelConfig,
    setConfig: React.Dispatch<React.SetStateAction<ModelConfig>>,
    models: { id: string; name: string }[],
    setModels: React.Dispatch<React.SetStateAction<{ id: string; name: string }[]>>,
    isFetching: boolean,
    setIsFetching: React.Dispatch<React.SetStateAction<boolean>>
  ) => (
    <div className="model-block">
      <div className="model-block-title">{title}</div>
      
      <div className="config-field">
        <label className="field-label">Base URL</label>
        <input
          className="config-input"
          value={config.base_url}
          onChange={e => setConfig({ ...config, base_url: e.target.value })}
          placeholder="https://api.openai.com/v1"
        />
      </div>

      <div className="config-field">
        <label className="field-label">API Key</label>
        <input
          className="config-input"
          type="password"
          value={config.api_key}
          onChange={e => setConfig({ ...config, api_key: e.target.value })}
          placeholder={config.api_key === '********' ? '已设置 (********)' : 'sk-...'}
        />
      </div>

      <div className="config-field">
        <label className="field-label">模型 ID</label>
        <select
          className="config-select"
          value={config.model_id}
          onChange={e => setConfig({ ...config, model_id: e.target.value })}
        >
          <option value="" disabled>请选择模型</option>
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        <button 
          className="fetch-models-btn"
          onClick={() => handleFetchModels(size, config, setModels, setIsFetching)}
          disabled={isFetching || !config.base_url}
        >
          {isFetching ? '获取中...' : '获取模型列表'}
        </button>
      </div>

      <div className="config-field">
        <label className="field-label">Max Tokens (0 表示无上限)</label>
        <input
          className="config-input"
          type="number"
          min="0"
          value={config.max_tokens}
          onChange={e => setConfig({ ...config, max_tokens: parseInt(e.target.value) || 0 })}
        />
      </div>

      <div className="config-field">
        <label className="field-label">Temperature</label>
        <input
          className="config-input"
          type="number"
          min="0"
          max="2"
          step="0.1"
          value={config.temperature}
          onChange={e => setConfig({ ...config, temperature: parseFloat(e.target.value) || 0 })}
        />
      </div>
    </div>
  );

  return (
    <div className="api-config-preset-panel">
      {error && <div className="config-error">{error}</div>}
      
      <div className="preset-management-area">
        <select 
          className="preset-select"
          value={selectedPresetId}
          onChange={e => handleSelectPreset(e.target.value)}
        >
          <option value="" disabled>-- 新预设 --</option>
          {presets.map(p => (
            <option key={p.id} value={p.id}>
              {p.name} {p.is_active ? '(当前激活)' : ''}
            </option>
          ))}
        </select>
        <div className="preset-actions">
          <button className="config-btn config-btn-secondary" onClick={handleNewPreset}>
            新增
          </button>
          <button className="config-btn config-btn-primary" onClick={handleSaveClick} disabled={isLoading}>
            保存并激活
          </button>
        </div>
      </div>

      <div className="models-container">
        {renderModelBlock('Large-Model', 'large', largeConfig, setLargeConfig, largeModels, setLargeModels, isFetchingLarge, setIsFetchingLarge)}
        {renderModelBlock('Medium-Model', 'medium', mediumConfig, setMediumConfig, mediumModels, setMediumModels, isFetchingMedium, setIsFetchingMedium)}
        {renderModelBlock('Small-Model', 'small', smallConfig, setSmallConfig, smallModels, setSmallModels, isFetchingSmall, setIsFetchingSmall)}
      </div>

      {showSaveDialog && (
        <div className="save-dialog-overlay">
          <div className="save-dialog">
            <h3>保存预设</h3>
            <div className="config-field">
              <label className="field-label">预设名称</label>
              <input
                className="config-input"
                value={newPresetName}
                onChange={e => setNewPresetName(e.target.value)}
                placeholder="例如：OpenAI 默认配置"
                autoFocus
              />
            </div>
            <div className="save-dialog-actions">
              <button className="config-btn config-btn-secondary" onClick={() => setShowSaveDialog(false)}>
                取消
              </button>
              <button className="config-btn config-btn-primary" onClick={handleConfirmSave} disabled={!newPresetName.trim() || isLoading}>
                确认保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
