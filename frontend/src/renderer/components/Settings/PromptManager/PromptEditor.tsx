/**
 * Prompt 编辑器组件
 * 做什么：基于 Monaco Editor 的 Jinja2 模板编辑器，支持保存为新版本。
 * 为什么这样做：提供代码高亮编辑体验，支持语法检查与变量提取。
 */
import React, { useCallback, useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { usePromptStore } from '../../../stores/promptStore';
import { PromptVersion } from '../../../types/prompt';

interface PromptEditorProps {
  /** 当前选中的版本（提供初始内容） */
  currentVersion: PromptVersion | null;
  /** 当前选中的模板 ID */
  templateId: string | null;
}

/** Jinja2 语言 ID 主题 */
const JINJA2_LANGUAGE = 'jinja2';

/** 编辑器 Monaco 配置 */
const EDITOR_OPTIONS = {
  minimap: { enabled: false },
  fontSize: 14,
  lineNumbers: 'on' as const,
  wordWrap: 'on' as const,
  scrollBeyondLastLine: false,
  automaticLayout: true,
  tabSize: 2,
};

export const PromptEditor: React.FC<PromptEditorProps> = ({ currentVersion, templateId }) => {
  const { selectedVersionId, createVersion, error } = usePromptStore();
  const [content, setContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // 当选中的版本变化时，更新编辑器内容
  useEffect(() => {
    if (currentVersion) {
      setContent(currentVersion.content);
    } else {
      setContent('');
    }
  }, [currentVersion]);

  /**
   * 从模板内容中提取 Jinja2 变量
   * 例：{{ user_name }} → ["user_name"]
   */
  const extractVariables = useCallback((text: string): string => {
    const matches = Array.from(text.matchAll(/\{\{(.*?)\}\}/g));
    const variables = matches.map((m) => m[1].trim());
    // 去重后以逗号拼接
    return [...new Set(variables)].join(',');
  }, []);

  /**
   * 保存为新版本
   */
  const handleSaveVersion = useCallback(async () => {
    if (!templateId) {
      setSaveError('请先选择一个模板');
      return;
    }
    if (!content.trim()) {
      setSaveError('模板内容不能为空');
      return;
    }

    setIsSaving(true);
    setSaveError(null);
    try {
      const variables = extractVariables(content);
      await createVersion(templateId, content, variables);
    } catch (err: any) {
      setSaveError(err.message || '保存版本失败');
    } finally {
      setIsSaving(false);
    }
  }, [templateId, content, extractVariables, createVersion]);

  /**
   * Monaco 编辑器挂载完成后的初始化
   */
  const handleEditorMount = useCallback((editor: any, monaco: any) => {
    // 注册 Jinja2 语法高亮（如果尚未注册）
    if (!monaco.languages.getLanguages().some((l: any) => l.id === JINJA2_LANGUAGE)) {
      monaco.languages.register({ id: JINJA2_LANGUAGE });

      // 定义 Jinja2 语法高亮规则
      monaco.languages.setMonarchTokensProvider(JINJA2_LANGUAGE, {
        tokenizer: {
          root: [
            [/\{\{.*?\}\}/, 'variable'],
            [/\{%-?.*?-?%}/, 'keyword'],
            [/\{#.*?#}/, 'comment'],
            [/".*?"/, 'string'],
            [/'.*?'/, 'string'],
            [/#.*$/, 'comment'],
          ],
        },
      });
    }
  }, []);

  if (!templateId) {
    return (
      <div className="prompt-editor">
        <h3>模板编辑器</h3>
        <div className="empty-panel">
          <div className="empty-text">请先选择一个模板</div>
        </div>
      </div>
    );
  }

  return (
    <div className="prompt-editor">
      <div className="prompt-editor-header">
        <h3>模板编辑器</h3>
        <span className="editor-version-info">
          {currentVersion ? `编辑 v${currentVersion.version_num}` : '新建版本'}
        </span>
      </div>

      <div className="editor-container">
        <Editor
          height="400px"
          language={JINJA2_LANGUAGE}
          value={content}
          onChange={(val) => setContent(val || '')}
          options={EDITOR_OPTIONS}
          onMount={handleEditorMount}
        />
      </div>

      <div className="editor-footer">
        <button
          className="config-btn config-btn-primary"
          onClick={handleSaveVersion}
          disabled={isSaving}
        >
          {isSaving ? '保存中...' : '保存为新版本'}
        </button>
        {saveError && <div className="config-error">{saveError}</div>}
        {error && !saveError && <div className="config-error">{error}</div>}
      </div>
    </div>
  );
};
