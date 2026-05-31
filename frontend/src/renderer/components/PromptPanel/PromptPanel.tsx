/**
 * Prompt 管理独立面板组件
 * 做什么：作为侧栏独立菜单项打开的 Prompt 模板管理面板。
 * 为什么这样做：根据用户要求，Prompt 管理从设置面板中分离，作为独立的侧栏菜单项。
 */
import React, { useState, useCallback } from 'react';
import { TemplateList } from '../Settings/PromptManager/TemplateList';
import { VersionHistory } from '../Settings/PromptManager/VersionHistory';
import { PromptEditor } from '../Settings/PromptManager/PromptEditor';
import { DiffViewer } from '../Settings/PromptManager/DiffViewer';
import { PromptPreview } from '../Settings/DebugPanel/PromptPreview';
import { PromptTemplate, PromptVersion } from '../../types/prompt';
import './PromptPanel.css';

type PromptTab = 'manage' | 'preview';

export const PromptPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PromptTab>('manage');
  const [selectedTemplate, setSelectedTemplate] = useState<PromptTemplate | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null);
  const [compareVersion, setCompareVersion] = useState<PromptVersion | null>(null);
  const [isDiffMode, setIsDiffMode] = useState(false);

  const handleSelectTemplate = useCallback((template: PromptTemplate) => {
    setSelectedTemplate(template);
    setSelectedVersion(null);
    setCompareVersion(null);
    setIsDiffMode(false);
  }, []);

  const handleSelectVersion = useCallback((version: PromptVersion) => {
    setSelectedVersion(version);
    setIsDiffMode(false);
  }, []);

  return (
    <div className="prompt-panel">
      <div className="settings-tabs">
        <button
          className={`settings-tab ${activeTab === 'manage' ? 'active' : ''}`}
          onClick={() => setActiveTab('manage')}
        >
          模板管理
        </button>
        <button
          className={`settings-tab ${activeTab === 'preview' ? 'active' : ''}`}
          onClick={() => setActiveTab('preview')}
        >
          调试预览
        </button>
      </div>

      <div className="settings-tab-content">
        {activeTab === 'manage' && (
          <div className="prompts-layout">
            {/* 左侧：模板列表 */}
            <div className="prompts-sidebar">
              <TemplateList
                onSelectTemplate={handleSelectTemplate}
                selectedTemplateId={selectedTemplate?.id ?? null}
              />
            </div>

            {/* 右侧：版本历史 + 编辑器/对比 */}
            <div className="prompts-main">
              <div className="prompts-version-history">
                <VersionHistory
                  templateId={selectedTemplate?.id ?? null}
                  onSelectVersion={handleSelectVersion}
                  selectedVersionId={selectedVersion?.id ?? null}
                />
                {selectedVersion && (
                  <div className="version-actions-bar">
                    <button
                      className={`config-btn config-btn-sm ${isDiffMode ? 'config-btn-primary' : 'config-btn-secondary'}`}
                      onClick={() => {
                        setIsDiffMode(!isDiffMode);
                        if (!isDiffMode && selectedVersion) {
                          setCompareVersion(null);
                        }
                      }}
                    >
                      {isDiffMode ? '退出对比' : '开启版本对比'}
                    </button>
                  </div>
                )}
              </div>

              {isDiffMode ? (
                <div className="prompts-diff">
                  <div className="diff-selectors">
                    <select
                      className="config-input config-input-sm"
                      value={compareVersion?.id ?? ''}
                      onChange={(e) => {
                        setCompareVersion(null);
                      }}
                    >
                      <option value="">选择对比的旧版本</option>
                    </select>
                  </div>
                  <DiffViewer oldVersion={compareVersion} newVersion={selectedVersion} />
                </div>
              ) : (
                <div className="prompts-editor">
                  <PromptEditor
                    currentVersion={selectedVersion}
                    templateId={selectedTemplate?.id ?? null}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'preview' && (
          <div className="settings-section debug-section">
            <PromptPreview />
          </div>
        )}
      </div>
    </div>
  );
};
