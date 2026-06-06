/**
 * Prompt 模板列表组件
 * 做什么：按业务场景分组展示所有 Prompt 模板，支持选中和创建新模板。
 */
import React, { useEffect, useCallback, useState } from 'react';
import { usePromptStore } from '../../../stores/promptStore';
import { PromptTemplate, SlotPosition, PromptCategory } from '../../../types/prompt';

interface TemplateListProps {
  /** 选中模板后的回调 */
  onSelectTemplate: (template: PromptTemplate) => void;
  /** 当前选中的模板 ID */
  selectedTemplateId: string | null;
}

/** 槽位中文映射 */
const SLOT_LABELS: Record<SlotPosition, string> = {
  system: '系统指令',
  memory: '记忆上下文',
  runtime: '运行时变量',
};

/** 场景中文映射 */
const CATEGORY_LABELS: Record<string, string> = {
  chat: '对话',
  summary: '总结',
};

/**
 * 按业务场景对模板进行分组
 */
function groupByCategory(templates: PromptTemplate[]): Map<string, PromptTemplate[]> {
  const groups = new Map<string, PromptTemplate[]>();
  for (const t of templates) {
    const existing = groups.get(t.category) || [];
    existing.push(t);
    groups.set(t.category, existing);
  }
  return groups;
}

export const TemplateList: React.FC<TemplateListProps> = ({
  onSelectTemplate,
  selectedTemplateId,
}) => {
  const { templates, isLoadingTemplates, error, fetchTemplates, createTemplate } = usePromptStore();

  // 新建模板表单状态
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState<PromptCategory>('chat');
  const [newSlot, setNewSlot] = useState<SlotPosition>('system');
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // 初始加载
  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) {
      setCreateError('模板名称不能为空');
      return;
    }
    setIsCreating(true);
    setCreateError(null);
    try {
      await createTemplate(newName.trim(), newCategory, newSlot, false);
      setShowCreateForm(false);
      setNewName('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setCreateError(message || '创建模板失败');
    } finally {
      setIsCreating(false);
    }
  }, [newName, newCategory, newSlot, createTemplate]);

  const grouped = groupByCategory(templates);

  if (isLoadingTemplates && templates.length === 0) {
    return <div className="prompt-list-loading">加载模板列表中...</div>;
  }

  if (error && templates.length === 0) {
    return <div className="prompt-list-error">加载失败: {error}</div>;
  }

  return (
    <div className="template-list">
      <div className="template-list-header">
        <h3>Prompt 模板</h3>
        <button
          className="config-btn config-btn-primary config-btn-sm"
          onClick={() => setShowCreateForm(!showCreateForm)}
        >
          {showCreateForm ? '取消' : '+ 新建模板'}
        </button>
      </div>

      {/* 新建模板表单 */}
      {showCreateForm && (
        <div className="create-template-form">
          <div className="config-field">
            <label className="field-label">模板名称</label>
            <input
              className="config-input"
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="my_prompt_template"
              disabled={isCreating}
            />
          </div>
          <div className="config-field">
            <label className="field-label">业务场景</label>
            <select
              className="config-input"
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value as PromptCategory)}
              disabled={isCreating}
            >
              <option value="chat">对话</option>
              <option value="summary">总结</option>
            </select>
          </div>
          <div className="config-field">
            <label className="field-label">槽位位置</label>
            <select
              className="config-input"
              value={newSlot}
              onChange={(e) => setNewSlot(e.target.value as SlotPosition)}
              disabled={isCreating}
            >
              <option value="system">系统指令</option>
              <option value="memory">记忆上下文</option>
              <option value="runtime">运行时变量</option>
            </select>
          </div>
          <button
            className="config-btn config-btn-primary config-btn-sm"
            onClick={handleCreate}
            disabled={isCreating}
          >
            {isCreating ? '创建中...' : '确认创建'}
          </button>
          {createError && <div className="config-error">{createError}</div>}
        </div>
      )}

      {/* 按场景分组的模板列表 */}
      {Array.from(grouped.entries()).map(([category, categoryTemplates]) => (
        <div key={category} className="template-category-group">
          <h4 className="category-title">
            {CATEGORY_LABELS[category] || category}
          </h4>
          <ul className="template-items">
            {categoryTemplates.map((t) => (
              <li
                key={t.id || t.name}
                className={`template-item ${selectedTemplateId === t.id ? 'selected' : ''}`}
                onClick={() => onSelectTemplate(t)}
              >
                <div className="template-item-name">{t.name}</div>
                <div className="template-item-meta">
                  <span className="template-slot-badge">{SLOT_LABELS[t.slot_position]}</span>
                  {t.is_system && <span className="template-system-badge">系统</span>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {templates.length === 0 && !isLoadingTemplates && (
        <div className="empty-panel">
          <div className="empty-text">暂无模板，请新建一个</div>
        </div>
      )}
    </div>
  );
};
