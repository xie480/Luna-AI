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

/** 场景中文映射：覆盖后端所有可能的 Prompt 分类值（含 PromptCategory 枚举 + simple 文件夹目录名） */
const CATEGORY_LABELS: Record<string, string> = {
  // 基础对话与总结
  chat: '对话',
  summary: '总结',
  short_summary: '短期总结',
  long_summary: '长期总结',
  // 输入重构
  input_reconstruction: '输入重构',
  input_reconstruction_simplified: '简化输入重构',
  // 证据评估
  evidence_evaluator: '证据评估',
  // 用户画像
  user_profile_extract: '用户画像提取',
  user_profile_summarize: '用户画像摘要',
  // MCP 技能三阶段
  mcp_skill_screening: '技能初筛',
  mcp_skill_loading: '技能加载',
  mcp_skill_execution: '技能执行',
  // MCP 资源与回退
  mcp_resource_extraction: '资源提取',
  mcp_skill_fallback_extraction: '技能回退提取',
  mcp_skill_execution_summary: '技能执行摘要',
  skill_execution_summary: '技能执行摘要',
  // MCP 意图、工具与评价
  mcp_intent_judge: '意图判断',
  mcp_intent_alignment: '意图对齐',
  mcp_tool_calling: '工具调用',
  mcp_tool_screening: '工具筛选',
  mcp_skill_memory: '技能记忆',
  mcp_evaluation: '技能评价',
  // DAG 引擎
  dag_plan_generation: 'DAG 计划生成',
  dag_skill_screening: 'DAG 技能筛选',
  dag_step_plan_generation: 'DAG 步骤计划生成',
  dag_tool_parameter_extraction: 'DAG 工具参数提取',
  dag_data_transform: 'DAG 数据转换',
  dag_state_evaluation: 'DAG 状态评估',
  dag_plan_replan: 'DAG 计划重规划',
  dag_result_compression: 'DAG 结果压缩',
  dag_plan_summary: 'DAG 计划摘要',
  dag_tool_memory: 'DAG 工具记忆',
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
