import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useApiConfigPresetStore } from '../../stores/apiConfigPresetStore';
import { ModelConfig } from '../../services/apiConfigPresetService';
import './ApiConfigPresetPanel.css';

const DEFAULT_MODEL_CONFIG: ModelConfig = {
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model_id: '',
  max_tokens: 16384,
  max_context_tokens: 128000,
  temperature: 0.7,
};

/**
 * 按钮状态机（核心逻辑）：
 *
 * 根据当前配置的生命周期状态，操作区按钮动态渲染：
 *
 * ┌──────────────────────────────────────────────────────────────────┐
 * │  状态枚举           │  selectedPresetId │  is_active  │ 按钮渲染 │
 * ├─────────────────────┼───────────────────┼─────────────┼──────────┤
 * │  ① 新建态（未入库）  │  '' (空字符串)     │  N/A        │ [保存]   │
 * │  ② 已入库 & 未激活   │  有效 ID          │  false      │ [保存] [激活] │
 * │  ③ 已入库 & 已激活   │  有效 ID          │  true       │ [保存] [当前激活]│
 * └──────────────────────────────────────────────────────────────────┘
 *
 * 全局排他性保证（后端层）：
 * 后端 set_active() 通过 UPDATE 将所有预设置为 is_active = false，
 * 再将目标预设置为激活，确保系统内同时只有一个激活配置。
 * 前端在"激活"确认弹窗中提示用户此排他性信息。
 */
export const ApiConfigPresetPanel: React.FC = () => {
  const {
    presets,
    isLoading,
    error,
    fetchPresets,
    createPreset,
    updatePreset,
    activatePreset,
    deletePreset,
    fetchModels,
  } = useApiConfigPresetStore();

  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);
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
  const [showActivateDialog, setShowActivateDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  // ==================== 状态机：派生状态 ====================

  /**
   * ① 新建态：selectedPresetId 被 handleNewPreset 设为空字符串 ''，
   * 表示当前编辑的是一份全新、尚未入库的配置。
   */
  const isNewPreset = selectedPresetId === '';

  /**
   * ②/③ 已入库态：当前选中的预设对象（如果已保存到后端）
   */
  const currentPreset = useMemo(
    () => (selectedPresetId && !isNewPreset ? presets.find(p => p.id === selectedPresetId) : undefined),
    [presets, selectedPresetId, isNewPreset]
  );

  /**
   * ③ 激活态：当前配置已入库且 is_active = true
   */
  const isCurrentActive = currentPreset?.is_active ?? false;

  // ==================== 事件处理 ====================

  const handleSelectPreset = useCallback((id: string) => {
    setSelectedPresetId(id);
    const preset = presets.find(p => p.id === id);
    if (preset) {
      setLargeConfig(preset.large_model_config);
      setMediumConfig(preset.medium_model_config);
      setSmallConfig(preset.small_model_config);
      // 切换预设时，用已保存的 model_id 初始化模型列表
      setLargeModels(preset.large_model_config.model_id ? [{ id: preset.large_model_config.model_id, name: preset.large_model_config.model_id }] : []);
      setMediumModels(preset.medium_model_config.model_id ? [{ id: preset.medium_model_config.model_id, name: preset.medium_model_config.model_id }] : []);
      setSmallModels(preset.small_model_config.model_id ? [{ id: preset.small_model_config.model_id, name: preset.small_model_config.model_id }] : []);
    }
  }, [presets]);

  // 初始化 / 列表变更时自动选中激活配置或第一个配置
  useEffect(() => {
    if (presets.length > 0) {
      if (selectedPresetId === null) {
        // 首次加载：选中已激活的配置，若无则选第一个
        const active = presets.find(p => p.is_active) || presets[0];
        handleSelectPreset(active.id);
      } else if (selectedPresetId !== '' && !presets.find(p => p.id === selectedPresetId)) {
        // 当前选中项被删除等场景，回退到激活配置或第一个
        const active = presets.find(p => p.is_active) || presets[0];
        handleSelectPreset(active.id);
      }
    }
  }, [presets, selectedPresetId, handleSelectPreset]);

  /**
   * 创建新配置：清空所有表单字段置为默认值，selectedPresetId 设为 ''（新建态）
   */
  const handleNewPreset = () => {
    setSelectedPresetId('');
    setLargeConfig({ ...DEFAULT_MODEL_CONFIG });
    setMediumConfig({ ...DEFAULT_MODEL_CONFIG });
    setSmallConfig({ ...DEFAULT_MODEL_CONFIG });
    setLargeModels([]);
    setMediumModels([]);
    setSmallModels([]);
  };

  /**
   * 点击"保存"按钮 → 打开保存确认弹窗
   * 新建态：弹出空白名称输入框
   * 已入库态：弹出预填当前预设名称的编辑框
   */
  const handleSaveClick = () => {
    const preset = presets.find(p => p.id === selectedPresetId);
    setNewPresetName(preset ? preset.name : '');
    setShowSaveDialog(true);
  };

  /**
   * 确认保存：将当前表单数据提交到后端
   * 新建 → 执行数据入库的新增接口调用
   * 已存在 → 执行数据更新的修改接口调用
   */
  const handleConfirmSave = async () => {
    if (!newPresetName.trim()) return;
    try {
      let id;
      if (isNewPreset) {
        id = await createPreset({
          id: '',
          name: newPresetName.trim(),
          large_model_config: largeConfig,
          medium_model_config: mediumConfig,
          small_model_config: smallConfig,
        });
      } else {
        id = await updatePreset({
          id: selectedPresetId || '',
          name: newPresetName.trim(),
          large_model_config: largeConfig,
          medium_model_config: mediumConfig,
          small_model_config: smallConfig,
        });
      }
      // 保存成功后选中该预设（切换到已入库态）
      setSelectedPresetId(id);
      setShowSaveDialog(false);
    } catch (e) {
      // Store 层已处理错误状态
    }
  };

  /**
   * 点击"激活"按钮 → 弹出全局排他性确认弹窗
   */
  const handleActivateClick = () => {
    setShowActivateDialog(true);
  };

  /**
   * 确认激活：调用后端激活接口
   * 后端保证全局排他性——全量置否后再激活目标
   */
  const handleConfirmActivate = async () => {
    if (!selectedPresetId) return;
    try {
      await activatePreset(selectedPresetId);
      setShowActivateDialog(false);
    } catch (e) {
      // Store 层已处理错误状态
    }
  };

  /**
   * 点击"删除"按钮 → 弹出删除确认弹窗
   */
  const handleDeleteClick = () => {
    setShowDeleteDialog(true);
  };

  /**
   * 确认删除：调用后端删除接口，删除成功后回退到第一个预设或新建态
   */
  const handleConfirmDelete = async () => {
    if (!selectedPresetId) return;
    try {
      await deletePreset(selectedPresetId);
      setShowDeleteDialog(false);
      // 删除后如果列表为空，自动进入新建态；否则选中第一个
      if (presets.length <= 1) {
        setSelectedPresetId('');
        setLargeConfig({ ...DEFAULT_MODEL_CONFIG });
        setMediumConfig({ ...DEFAULT_MODEL_CONFIG });
        setSmallConfig({ ...DEFAULT_MODEL_CONFIG });
        setLargeModels([]);
        setMediumModels([]);
        setSmallModels([]);
      }
    } catch (e) {
      // Store 层已处理错误状态
    }
  };

  // ==================== 按钮状态机渲染 ====================

  /**
   * 渲染操作区按钮
   * 
   * 状态机决策树：
   *   ① isNewPreset === true       → 仅渲染 [保存]
   *   ② currentPreset && !active   → 渲染 [保存] + [激活]
   *   ③ currentPreset && active    → 渲染 [保存] + [当前激活](禁用)
   */
  const renderActionButtons = () => {
    // ① 新建态：仅显示"保存"按钮
    if (isNewPreset) {
      return (
        <button
          className="config-btn config-btn-primary"
          onClick={handleSaveClick}
          disabled={isLoading}
        >
          保存
        </button>
      );
    }

    // 已入库态（② 或 ③）："保存"按钮始终可用（用于更新配置）
    return (
      <>
        <button
          className="config-btn config-btn-primary"
          onClick={handleSaveClick}
          disabled={isLoading}
        >
          保存
        </button>
        <button
          className={`config-btn ${isCurrentActive ? 'config-btn-activated' : 'config-btn-accent'}`}
          onClick={handleActivateClick}
          disabled={isLoading || isCurrentActive}
          title={
            isCurrentActive
              ? '当前配置已激活，无需重复操作'
              : '激活此配置将自动取消其他配置的激活状态'
          }
        >
          {isCurrentActive ? '当前激活' : '激活'}
        </button>
        <button
          className="config-btn config-btn-danger"
          onClick={handleDeleteClick}
          disabled={isLoading}
          title="删除此配置预设"
        >
          删除
        </button>
      </>
    );
  };

  // ==================== 模型区块渲染 ====================

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
        <label className="field-label">Max Context Tokens（上下文窗口上限）</label>
        <input
          className="config-input"
          type="number"
          min="0"
          value={config.max_context_tokens}
          onChange={e => setConfig({ ...config, max_context_tokens: parseInt(e.target.value) || 0 })}
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

  // ==================== 渲染 ====================

  return (
    <div className="api-config-preset-panel">
      {error && <div className="config-error">{error}</div>}

      {/* 预设选择与管理区 */}
      <div className="preset-management-area">
        <select
          className="preset-select"
          value={selectedPresetId || ''}
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
          {/* ★ 状态机驱动：根据当前状态动态渲染按钮组 */}
          {renderActionButtons()}
        </div>
      </div>

      {/* 三模型配置区块 */}
      <div className="models-container">
        {renderModelBlock('Large-Model', 'large', largeConfig, setLargeConfig, largeModels, setLargeModels, isFetchingLarge, setIsFetchingLarge)}
        {renderModelBlock('Medium-Model', 'medium', mediumConfig, setMediumConfig, mediumModels, setMediumModels, isFetchingMedium, setIsFetchingMedium)}
        {renderModelBlock('Small-Model', 'small', smallConfig, setSmallConfig, smallModels, setSmallModels, isFetchingSmall, setIsFetchingSmall)}
      </div>

      {/* 保存确认弹窗 */}
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
              <button
                className="config-btn config-btn-primary"
                onClick={handleConfirmSave}
                disabled={!newPresetName.trim() || isLoading}
              >
                确认保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 激活确认弹窗（含全局排他性提示） */}
      {showActivateDialog && (
        <div className="save-dialog-overlay">
          <div className="save-dialog">
            <h3>确认激活</h3>
            <div className="config-field">
              <p style={{ fontSize: '14px', color: 'var(--text-primary)', lineHeight: '1.5', margin: 0 }}>
                确定要激活此配置吗？<br/><br/>
                <strong>⚠️ 全局排他性提醒：</strong><br/>
                系统内同时只能存在<strong>一个</strong>处于激活状态的 API 配置。<br/>
                激活此配置将<strong>自动取消</strong>其他配置的激活状态。<br/><br/>
                当前待取消的配置：
              </p>
              {/* 列出当前其他已激活的配置 */}
              <ul style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.6', margin: '8px 0 0 0', paddingLeft: '20px' }}>
                {presets
                  .filter(p => p.is_active && p.id !== selectedPresetId)
                  .map(p => (
                    <li key={p.id}>{p.name}</li>
                  ))
                }
                {presets.filter(p => p.is_active && p.id !== selectedPresetId).length === 0 && (
                  <li style={{ listStyle: 'none', marginLeft: '-20px' }}>（当前无其他已激活配置）</li>
                )}
              </ul>
            </div>
            <div className="save-dialog-actions">
              <button className="config-btn config-btn-secondary" onClick={() => setShowActivateDialog(false)}>
                取消
              </button>
              <button
                className="config-btn config-btn-accent"
                onClick={handleConfirmActivate}
                disabled={isLoading}
              >
                确认激活
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {showDeleteDialog && (
        <div className="save-dialog-overlay">
          <div className="save-dialog">
            <h3>确认删除</h3>
            <div className="config-field">
              <p style={{ fontSize: '14px', color: 'var(--text-primary)', lineHeight: '1.5', margin: 0 }}>
                确定要删除预设 <strong>"{currentPreset?.name}"</strong> 吗？<br/><br/>
                此操作不可恢复，删除后该配置将永久丢失。
              </p>
            </div>
            <div className="save-dialog-actions">
              <button className="config-btn config-btn-secondary" onClick={() => setShowDeleteDialog(false)}>
                取消
              </button>
              <button
                className="config-btn config-btn-danger"
                onClick={handleConfirmDelete}
                disabled={isLoading}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
