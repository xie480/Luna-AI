/**
 * Prompt 预览调试组件
 * 做什么：允许开发者手动输入模拟的上下文变量，预览 Jinja2 渲染后的完整 Prompt。
 * 为什么这样做：便于排查变量缺失或渲染错误问题。
 * 注意：依赖后端提供的 Dry Run 接口，当前为预留实现。
 */
import React, { useState, useCallback } from 'react';
import { usePromptStore } from '../../../stores/promptStore';

interface ContextVariable {
  key: string;
  value: string;
}

export const PromptPreview: React.FC = () => {
  const { selectedVersionId, versions } = usePromptStore();

  const [variables, setVariables] = useState<ContextVariable[]>([]);
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentVersion = versions.find((v) => v.id === selectedVersionId);

  /**
   * 添加上下文变量
   */
  const handleAddVariable = useCallback(() => {
    if (!newKey.trim()) return;
    // 检查是否已存在同名变量
    if (variables.some((v) => v.key === newKey.trim())) {
      setError(`变量 "${newKey.trim()}" 已存在`);
      return;
    }
    setVariables((prev) => [...prev, { key: newKey.trim(), value: newValue }]);
    setNewKey('');
    setNewValue('');
    setError(null);
  }, [newKey, newValue, variables]);

  /**
   * 移除上下文变量
   */
  const handleRemoveVariable = useCallback((key: string) => {
    setVariables((prev) => prev.filter((v) => v.key !== key));
  }, []);

  /**
   * 请求 Dry Run 预览
   * 注意：后端 Dry Run 接口尚未实现，此方法为占位逻辑
   */
  const handlePreview = useCallback(async () => {
    if (!currentVersion) {
      setError('请先选择一个版本');
      return;
    }

    setIsLoading(true);
    setError(null);
    setPreviewResult(null);

    try {
      // 构建模拟上下文对象
      const contextObj: Record<string, string> = {};
      for (const v of variables) {
        contextObj[v.key] = v.value;
      }

      // TODO: 调用后端 Dry Run 接口
      // const res = await fetch('/api/v1/prompts/dry-run', {
      //   method: 'POST',
      //   headers: { 'Content-Type': 'application/json' },
      //   body: JSON.stringify({
      //     template_id: currentVersion.template_id,
      //     version_id: currentVersion.id,
      //     context: contextObj,
      //   }),
      // });
      // const data = await res.json();
      // setPreviewResult(data.rendered);

      // 占位：直接显示模板内容
      let rendered = currentVersion.content;
      for (const v of variables) {
        rendered = rendered.replaceAll(`{{ ${v.key} }}`, v.value);
        rendered = rendered.replaceAll(`{{${v.key}}}`, v.value);
      }
      // 延迟模拟请求
      await new Promise((resolve) => setTimeout(resolve, 300));
      setPreviewResult(rendered);
    } catch (err: any) {
      setError(err.message || '预览请求失败');
    } finally {
      setIsLoading(false);
    }
  }, [currentVersion, variables]);

  return (
    <div className="prompt-preview">
      <h3>Prompt 预览与调试</h3>
      <p className="preview-description">
        在此模拟上下文变量，预览 Jinja2 渲染后的完整 Prompt 内容。
        注意：当前为前端模拟渲染，后端 Dry Run 接口尚未就绪时将使用简易变量替换。
      </p>

      <div className="preview-layout">
        {/* 左侧：上下文变量编辑 */}
        <div className="preview-variables">
          <h4>上下文变量</h4>

          {/* 变量列表 */}
          <div className="variables-list">
            {variables.map((v) => (
              <div key={v.key} className="variable-item">
                <span className="variable-key">{v.key}</span>
                <span className="variable-value">{v.value}</span>
                <button
                  className="variable-remove-btn"
                  onClick={() => handleRemoveVariable(v.key)}
                  title="移除"
                >
                  ✕
                </button>
              </div>
            ))}
            {variables.length === 0 && (
              <div className="empty-text">暂无变量，请添加</div>
            )}
          </div>

          {/* 添加变量表单 */}
          <div className="add-variable-form">
            <input
              className="config-input config-input-sm"
              type="text"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="变量名 (如 user_name)"
            />
            <input
              className="config-input config-input-sm"
              type="text"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder="变量值"
            />
            <button
              className="config-btn config-btn-primary config-btn-sm"
              onClick={handleAddVariable}
              disabled={!newKey.trim()}
            >
              添加
            </button>
          </div>
        </div>

        {/* 右侧：预览结果 */}
        <div className="preview-result">
          <h4>渲染结果</h4>
          <div className="preview-actions">
            <button
              className="config-btn config-btn-primary"
              onClick={handlePreview}
              disabled={isLoading || !currentVersion}
            >
              {isLoading ? '渲染中...' : '运行预览'}
            </button>
          </div>
          {error && <div className="config-error">{error}</div>}
          {previewResult !== null && (
            <pre className="preview-output">{previewResult}</pre>
          )}
          {!currentVersion && (
            <div className="empty-text">请先在 Prompt 管理中选择一个模板版本</div>
          )}
        </div>
      </div>
    </div>
  );
};
