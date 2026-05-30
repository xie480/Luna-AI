/**
 * 版本差异对比组件
 * 做什么：基于 Monaco Editor 对比两个 Prompt 版本的内容差异。
 * 为什么这样做：方便用户直观查看版本之间的变更，支持回滚决策。
 */
import React, { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { PromptVersion } from '../../../types/prompt';

interface DiffViewerProps {
  /** 旧版本（左侧） */
  oldVersion: PromptVersion | null;
  /** 新版本（右侧） */
  newVersion: PromptVersion | null;
}

const DIFF_OPTIONS = {
  fontSize: 13,
  lineNumbers: 'on' as const,
  wordWrap: 'on' as const,
  scrollBeyondLastLine: false,
  automaticLayout: true,
  renderSideBySide: true,
  readOnly: true,
  minimap: { enabled: false },
};

export const DiffViewer: React.FC<DiffViewerProps> = ({ oldVersion, newVersion }) => {
  const [diffLanguage, setDiffLanguage] = useState('jinja2');

  // 确保 diff 语言设置
  useEffect(() => {
    setDiffLanguage('jinja2');
  }, [oldVersion, newVersion]);

  if (!oldVersion && !newVersion) {
    return (
      <div className="diff-viewer">
        <h3>版本差异对比</h3>
        <div className="empty-panel">
          <div className="empty-text">请选择两个版本进行对比</div>
        </div>
      </div>
    );
  }

  if (!oldVersion || !newVersion) {
    return (
      <div className="diff-viewer">
        <h3>版本差异对比</h3>
        <div className="empty-panel">
          <div className="empty-text">请选择两个不同的版本进行对比</div>
        </div>
      </div>
    );
  }

  return (
    <div className="diff-viewer">
      <div className="diff-viewer-header">
        <h3>版本差异对比</h3>
        <div className="diff-versions-info">
          <span className="diff-old-version">旧版本: v{oldVersion.version_num}</span>
          <span className="diff-arrow">→</span>
          <span className="diff-new-version">新版本: v{newVersion.version_num}</span>
        </div>
      </div>

      <div className="diff-editor-container">
        <Editor
          height="400px"
          language={diffLanguage}
          original={oldVersion.content}
          modified={newVersion.content}
          options={DIFF_OPTIONS}
        />
      </div>

      <div className="diff-footer">
        <span className="diff-meta">
          旧版本创建时间: {new Date(oldVersion.created_at).toLocaleString('zh-CN')}
          &nbsp;|&nbsp;
          新版本创建时间: {new Date(newVersion.created_at).toLocaleString('zh-CN')}
        </span>
      </div>
    </div>
  );
};
