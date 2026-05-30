/**
 * 设置面板根组件
 * 做什么：聚合 GeneralConfig（API Key 与模型配置）、DebugPanel（调试预览）两个子模块，
 * 通过内部 Tab 切换实现多视图路由。Prompt 管理已移至独立侧栏菜单项。
 */
import React, { useState, useCallback, useEffect } from 'react';
import { useConfigStore } from '../../stores/configStore';
import { ApiKeyInput } from './GeneralConfig/ApiKeyInput';
import { ModelSelector } from './GeneralConfig/ModelSelector';
import { PromptPreview } from './DebugPanel/PromptPreview';

/** 设置面板 Tab 类型 */
type SettingsTab = 'general' | 'debug';

/** Tab 配置 */
interface TabConfig {
  id: SettingsTab;
  label: string;
}

const TABS: TabConfig[] = [
  { id: 'general', label: '全局配置' },
  { id: 'debug', label: '调试预览' },
];

export const SettingsPanel: React.FC = () => {
  const { fetchConfig } = useConfigStore();
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');

  // 初始加载配置
  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return (
    <div className="settings-panel">
      {/* Tab 导航栏 */}
      <div className="settings-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`settings-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 内容区 */}
      <div className="settings-tab-content">
        {/* === 全局配置 Tab === */}
        {activeTab === 'general' && (
          <div className="settings-section general-config-section">
            <div className="section-card">
              <ApiKeyInput />
              <div className="section-divider" />
              <ModelSelector />
            </div>
          </div>
        )}

        {/* === 调试预览 Tab === */}
        {activeTab === 'debug' && (
          <div className="settings-section debug-section">
            <PromptPreview />
          </div>
        )}
      </div>
    </div>
  );
};
