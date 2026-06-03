/**
 * 版本差异对比组件
 * 做什么：基于 Monaco DiffEditor 对比两个 Prompt 版本的内容差异。
 * 为什么这样做：DiffEditor 原生支持双栏对比视图与差异高亮，新增行为绿色、删除行为红色。
 * 使用 Editor + original/modified props 方式在 v4.7.0 中可能导致渲染空白，
 * 而 DiffEditor 组件是专门为差异对比设计的组件，能正确渲染。
 */
import React, { useEffect, useRef } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { PromptVersion } from '../../../types/prompt';

interface DiffViewerProps {
  /** 旧版本（左侧） */
  oldVersion: PromptVersion | null;
  /** 新版本（右侧） */
  newVersion: PromptVersion | null;
}

/**
 * Monaco DiffEditor 配置选项
 */
/**
 * Monaco DiffEditor 配置选项
 * wordWrap: 'off' — 强制关闭两侧换行，确保左右两侧换行行为完全一致。
 * 若开启 wordWrap，Monaco DiffEditor 在部分版本中会出现左侧不换行而右侧换行的 bug，
 * 导致同一行内容因视觉换行位置不同而产生虚假的红色差异高亮和行号错位。
 * 关闭换行后，长内容通过水平滚动条查看，差异对比基于实际行内容，
 * 只高亮真正有差异的行，消除一切因换行不一致引起的误报。
 */
const DIFF_OPTIONS = {
  fontSize: 13,
  lineNumbers: 'on' as const,
  wordWrap: 'off' as const,
  scrollBeyondLastLine: true,
  automaticLayout: true,
  renderSideBySide: true,
  readOnly: true,
  minimap: { enabled: false },
  diffAlgorithm: 'advanced',
  enableSplitViewResizing: false,
  originalEditable: false,
  renderOverviewRuler: true,
  overviewRulerBorder: false,
};

/** 模块级标志位，确保自定义主题只注册一次 */
let _themeRegistered = false;

/**
 * 注册自定义差异对比主题
 * 插入行（新增）→ 绿色
 * 删除行（删除）→ 红色
 */
function registerDiffTheme(monaco: any): void {
  if (_themeRegistered) return;
  _themeRegistered = true;

  monaco.editor.defineTheme('luna-diff-theme', {
    base: 'vs-dark',
    inherit: true,
    rules: [],
    colors: {
      // 插入（新增）行 — 绿色
      'diffEditor.insertedTextBackground': 'rgba(34, 197, 94, 0.15)',
      'diffEditor.insertedTextBorder': 'rgba(34, 197, 94, 0.3)',
      'diffEditor.insertedLineBackground': 'rgba(34, 197, 94, 0.08)',
      'diffEditorOverview.insertedForeground': '#22c55e',
      // 删除行 — 红色
      'diffEditor.removedTextBackground': 'rgba(239, 68, 68, 0.15)',
      'diffEditor.removedTextBorder': 'rgba(239, 68, 68, 0.3)',
      'diffEditor.removedLineBackground': 'rgba(239, 68, 68, 0.08)',
      'diffEditorOverview.removedForeground': '#ef4444',
      // 缝隙填充
      'diffEditor.diagonalFill': 'rgba(255, 255, 255, 0.05)',
    },
  });
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ oldVersion, newVersion }) => {
  const editorRef = useRef<any>(null);

  /**
   * DiffEditor 挂载后的初始化回调
   * 注册自定义主题并设置差异高亮颜色
   */
  const handleDiffEditorMount = (editor: any, monaco: any) => {
    editorRef.current = editor;
    registerDiffTheme(monaco);
    monaco.editor.setTheme('luna-diff-theme');
  };

  // 当版本数据变化时刷新编辑器，确保差异对比正确重新计算
  useEffect(() => {
    if (editorRef.current) {
      const timer = setTimeout(() => {
        editorRef.current?.updateOptions({});
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [oldVersion, newVersion]);

  // 无任何版本时显示空状态提示
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

  // 仅有一个版本时提示
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
        <DiffEditor
          height="400px"
          language="jinja2"
          original={oldVersion.content}
          modified={newVersion.content}
          options={DIFF_OPTIONS}
          onMount={handleDiffEditorMount}
          theme="luna-diff-theme"
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
