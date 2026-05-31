/**
 * 设置面板根组件
 * 做什么：聚合 GeneralConfig（API Key 与模型配置）子模块。
 * Prompt 管理和调试预览已移至独立侧栏菜单项。
 */
import React from 'react';
import { ApiConfigPresetPanel } from './ApiConfigPresetPanel';

export const SettingsPanel: React.FC = () => {
  return (
    <div className="settings-panel">
      <div className="settings-section general-config-section">
        <div className="section-card">
          <ApiConfigPresetPanel />
        </div>
      </div>
    </div>
  );
};
