/**
 * Luna AI Prompt 管理状态
 * 做什么：管理 Prompt 模板列表、选中状态、版本历史等 UI 状态。
 * 为什么这样做：将复杂的 UI 状态与组件解耦，方便在不同组件间共享数据。
 */
import { create } from 'zustand';
import { PromptTemplate, PromptVersion } from '../types/prompt';
import { promptService } from '../services/promptService';

interface PromptState {
  /** 模板列表 */
  templates: PromptTemplate[];
  /** 当前选中的模板 ID */
  selectedTemplateId: string | null;
  /** 当前选中模板的版本历史 */
  versions: PromptVersion[];
  /** 当前选中的版本 ID（用于预览或 Diff） */
  selectedVersionId: string | null;
  
  isLoadingTemplates: boolean;
  isLoadingVersions: boolean;
  error: string | null;

  /** 获取所有模板 */
  fetchTemplates: () => Promise<void>;
  /** 选择模板并获取其版本历史 */
  selectTemplate: (templateId: string) => Promise<void>;
  /** 选择版本 */
  selectVersion: (versionId: string) => void;
  /** 创建新模板 */
  createTemplate: (name: string, category: string, slotPosition: string, isSystem: boolean) => Promise<void>;
  /** 创建新版本 */
  createVersion: (templateId: string, content: string, variables: string) => Promise<void>;
  /** 发布版本 */
  publishVersion: (templateId: string, versionId: string) => Promise<void>;
  /** 回滚版本 */
  rollbackVersion: (templateId: string, versionId: string) => Promise<void>;
}

export const usePromptStore = create<PromptState>((set, get) => ({
  templates: [],
  selectedTemplateId: null,
  versions: [],
  selectedVersionId: null,
  
  isLoadingTemplates: false,
  isLoadingVersions: false,
  error: null,

  fetchTemplates: async () => {
    set({ isLoadingTemplates: true, error: null });
    try {
      const data = await promptService.getTemplates();
      set({ templates: data, isLoadingTemplates: false });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to load templates', isLoadingTemplates: false });
    }
  },

  selectTemplate: async (templateId) => {
    set({ selectedTemplateId: templateId, isLoadingVersions: true, error: null, versions: [], selectedVersionId: null });
    try {
      const data = await promptService.getVersions(templateId);
      set({ versions: data, isLoadingVersions: false });
      // 默认选中 active_version
      const template = get().templates.find(t => t.id === templateId);
      if (template && template.active_version_id) {
        set({ selectedVersionId: template.active_version_id });
      } else if (data.length > 0) {
        set({ selectedVersionId: data[0].id });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to load versions', isLoadingVersions: false });
    }
  },

  selectVersion: (versionId) => {
    set({ selectedVersionId: versionId });
  },

  createTemplate: async (name, category, slotPosition, isSystem) => {
    set({ error: null });
    try {
      await promptService.createTemplate(name, category, slotPosition, isSystem);
      await get().fetchTemplates();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to create template' });
      throw err;
    }
  },

  createVersion: async (templateId, content, variables) => {
    set({ error: null });
    try {
      await promptService.createVersion(templateId, content, variables);
      // 重新获取版本历史
      if (get().selectedTemplateId === templateId) {
        await get().selectTemplate(templateId);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to create version' });
      throw err;
    }
  },

  publishVersion: async (templateId, versionId) => {
    set({ error: null });
    try {
      await promptService.publishVersion(templateId, versionId);
      // 重新获取模板列表和版本历史以更新状态
      await get().fetchTemplates();
      if (get().selectedTemplateId === templateId) {
        await get().selectTemplate(templateId);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to publish version' });
      throw err;
    }
  },

  rollbackVersion: async (templateId, versionId) => {
    set({ error: null });
    try {
      await promptService.rollbackVersion(templateId, versionId);
      // 重新获取模板列表和版本历史以更新状态
      await get().fetchTemplates();
      if (get().selectedTemplateId === templateId) {
        await get().selectTemplate(templateId);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      set({ error: message || 'Failed to rollback version' });
      throw err;
    }
  },
}));
