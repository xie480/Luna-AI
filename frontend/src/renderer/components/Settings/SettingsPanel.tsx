/**
 * 设置面板根组件
 * 做什么：聚合 GeneralConfig（API Key 与模型配置）子模块。
 * Prompt 管理和调试预览已移至独立侧栏菜单项。
 */
import React, { useEffect } from 'react';
import { useConfigStore } from '../../stores/configStore';
import { ApiKeyInput } from './GeneralConfig/ApiKeyInput';
import { ModelSelector } from './GeneralConfig/ModelSelector';

export const SettingsPanel: React.FC = () => {
  const { fetchConfig } = useConfigStore();

  // 初始加载配置
  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return (
    <div className="settings-panel">
      <div className="settings-section general-config-section">
        <div className="section-card">
          <ApiKeyInput />
          <div className="section-divider" />
          <ModelSelector />
        </div>
      </div>
    </div>
  );
};
