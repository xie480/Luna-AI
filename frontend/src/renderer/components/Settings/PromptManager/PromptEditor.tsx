/**
 * Prompt 编辑器组件
 * 做什么：基于 Monaco Editor 的 Jinja2 模板编辑器，支持保存为新版本。
 * 为什么这样做：提供代码高亮编辑体验，支持语法检查与变量提取。
 */
import React, { useCallback, useState, useEffect, useRef } from 'react';
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
  contextmenu: false, // 禁用右键菜单以防止绕过只读限制
  dragAndDrop: false, // 禁用拖拽以防止绕过只读限制
  padding: { top: 16, bottom: 16 },
};

export const PromptEditor: React.FC<PromptEditorProps> = ({ currentVersion, templateId }) => {
  const { createVersion, error } = usePromptStore();
  const [initialContent, setInitialContent] = useState('');
  const [content, setContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const editorRef = useRef<any>(null);
  const monacoRef = useRef<any>(null);
  const decorationsRef = useRef<string[]>([]);

  const isDirty = content !== initialContent;

  // 当选中的版本变化时，更新编辑器内容
  useEffect(() => {
    if (currentVersion) {
      setContent(currentVersion.content);
      setInitialContent(currentVersion.content);
    } else {
      setContent('');
      setInitialContent('');
    }
    setSaveError(null);
  }, [currentVersion]);

  const handleReset = useCallback(() => {
    setContent(initialContent);
    setSaveError(null);
  }, [initialContent]);

  const updateDecorations = useCallback(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco) return;

    const model = editor.getModel();
    if (!model) return;

    const lines = model.getLinesContent();
    const newDecorations: any[] = [];

    lines.forEach((line: string, index: number) => {
      if (/\{\{.*?\}\}/.test(line) || /\{%.*?%\}/.test(line)) {
        newDecorations.push({
          range: new monaco.Range(index + 1, 1, index + 1, 1),
          options: {
            isWholeLine: true,
            className: 'readonly-line-decoration',
            marginClassName: 'readonly-line-margin',
          }
        });
      }
    });

    decorationsRef.current = editor.deltaDecorations(decorationsRef.current, newDecorations);
  }, []);

  useEffect(() => {
    updateDecorations();
  }, [content, updateDecorations]);

  /**
   * 从模板内容中提取 Jinja2 变量
   * 例：{{ user_name }} → ["user_name"]
   */
  const extractVariables = useCallback((text: string): string => {
    const matches = Array.from(text.matchAll(/\{\{(.*?)\}\}/g));
    const variables = matches.map((m) => m[1].trim());
    // 去重后转为 JSON 数组字符串，以匹配后端 jsonb 字段要求
    return JSON.stringify([...new Set(variables)]);
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
    editorRef.current = editor;
    monacoRef.current = monaco;

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

    // 拦截键盘事件以实现行级只读
    editor.onKeyDown((e: any) => {
      const selections = editor.getSelections();
      if (!selections) return;
      const model = editor.getModel();
      if (!model) return;

      let isReadOnly = false;
      for (const selection of selections) {
        let startLine = selection.startLineNumber;
        let endLine = selection.endLineNumber;

        if (selection.isEmpty()) {
          if (e.keyCode === monaco.KeyCode.Backspace && selection.startColumn === 1) {
            startLine = Math.max(1, startLine - 1);
          }
          if (e.keyCode === monaco.KeyCode.Delete && selection.startColumn === model.getLineMaxColumn(startLine)) {
            endLine = Math.min(model.getLineCount(), endLine + 1);
          }
        }

        for (let i = startLine; i <= endLine; i++) {
          const lineContent = model.getLineContent(i);
          if (/\{\{.*?\}\}/.test(lineContent) || /\{%.*?%\}/.test(lineContent)) {
            isReadOnly = true;
            break;
          }
        }
        if (isReadOnly) break;
      }

      const isNavigation = [
        monaco.KeyCode.LeftArrow, monaco.KeyCode.RightArrow, monaco.KeyCode.UpArrow, monaco.KeyCode.DownArrow,
        monaco.KeyCode.PageUp, monaco.KeyCode.PageDown, monaco.KeyCode.Home, monaco.KeyCode.End
      ].includes(e.keyCode);

      const isCopy = (e.ctrlKey || e.metaKey) && e.keyCode === monaco.KeyCode.KeyC;
      const isSelectAll = (e.ctrlKey || e.metaKey) && e.keyCode === monaco.KeyCode.KeyA;

      if (isReadOnly && !isNavigation && !isCopy && !isSelectAll) {
        e.preventDefault();
        e.stopPropagation();
      }
    });

    updateDecorations();
  }, [updateDecorations]);

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
    <div className="prompt-editor" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, height: '100%' }}>
      <div className="prompt-editor-header">
        <div className="editor-header-left">
          <h3>模板编辑器</h3>
          <span className="editor-version-info">
            {currentVersion ? `基于 v${currentVersion.version_num}` : '新建版本'}
          </span>
        </div>
        {isDirty && (
          <div className="editor-header-actions">
            <button
              className="config-btn config-btn-secondary config-btn-sm"
              onClick={handleReset}
              disabled={isSaving}
            >
              重置
            </button>
            <button
              className="config-btn config-btn-primary config-btn-sm"
              onClick={handleSaveVersion}
              disabled={isSaving}
            >
              {isSaving ? '保存中...' : '保存为新版本'}
            </button>
          </div>
        )}
      </div>

      <div className="editor-container" style={{ flex: 1, minHeight: 0, border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '8px', overflow: 'hidden' }}>
        <Editor
          height="100%"
          language={JINJA2_LANGUAGE}
          value={content}
          onChange={(val) => setContent(val || '')}
          options={EDITOR_OPTIONS}
          onMount={handleEditorMount}
        />
      </div>

      {(saveError || error) && (
        <div className="editor-footer">
          {saveError && <div className="config-error">{saveError}</div>}
          {error && !saveError && <div className="config-error">{error}</div>}
        </div>
      )}
    </div>
  );
};
