/**
 * MCP Skill 状态 Store。
 *
 * 做什么：管理 MCP Skill 面板的全局状态。
 * 为什么这样做：Skill 列表需要跨组件共享（列表组件、添加表单、状态指示器）。
 * 边界条件：组件卸载时不重置状态，由面板生命周期管理。
 * 异常行为：后端查询失败时保持上次成功加载的缓存。
 */

import { create } from 'zustand';
import type { SkillInfo, BatchImportResult } from '../../shared/types';
import * as mcpSkillService from '../services/mcpSkillService';

/**
 * Skill Store 状态和动作接口。
 */
interface SkillStoreState {
  /** 已注册的 Skill 列表。 */
  skills: SkillInfo[];
  /** 是否正在加载列表。 */
  isLoading: boolean;
  /** 加载错误信息。 */
  loadError: string;
  /** 注册配置的提交状态。 */
  submitStatus: 'idle' | 'submitting' | 'success' | 'error';
  /** 提交错误信息。 */
  submitError: string;
  /** 批量导入状态。 */
  importStatus: 'idle' | 'importing' | 'success' | 'error';
  /** 批量导入结果。 */
  importResult: BatchImportResult | null;

  /** 加载 Skill 列表。 */
  loadSkills: () => Promise<void>;
  /** 注册单个 Skill。 */
  registerSkill: (config: mcpSkillService.SkillConfig) => Promise<void>;
  /** 批量注册 Skill。 */
  batchRegisterSkills: (configs: mcpSkillService.SkillConfig[]) => Promise<BatchImportResult>;
  /** 更新 Skill 配置。 */
  updateSkill: (skillId: string, config: mcpSkillService.UpdateSkillRequest) => Promise<void>;
  /** 删除 Skill。 */
  deleteSkill: (skillId: string) => Promise<void>;
  /** 重置提交状态。 */
  resetSubmitStatus: () => void;
  /** 重置导入状态。 */
  resetImportStatus: () => void;
}

export const useSkillStore = create<SkillStoreState>((set, get) => ({
  skills: [],
  isLoading: false,
  loadError: '',
  submitStatus: 'idle',
  submitError: '',
  importStatus: 'idle',
  importResult: null,

  loadSkills: async () => {
    set({ isLoading: true, loadError: '' });
    try {
      const serverSkills = await mcpSkillService.listSkills();
      // 转换为前端的 SkillInfo 类型
      const skills: SkillInfo[] = serverSkills.map((s) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        version: s.version,
        enabled: s.enabled,
        metadata: s.metadata,
        createdAt: s.created_at,
        updatedAt: s.updated_at,
      }));
      set({ skills, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        loadError: error instanceof Error ? error.message : '加载 MCP Skill 列表失败',
      });
    }
  },

  registerSkill: async (config) => {
    set({ submitStatus: 'submitting', submitError: '' });
    try {
      await mcpSkillService.registerSkill(config);
      set({ submitStatus: 'success' });
      // 注册成功后重新加载列表
      await get().loadSkills();
    } catch (error) {
      set({
        submitStatus: 'error',
        submitError: error instanceof Error ? error.message : '注册失败',
      });
      throw error;
    }
  },

  batchRegisterSkills: async (configs) => {
    set({ importStatus: 'importing', importResult: null });
    try {
      const result = await mcpSkillService.batchRegisterSkills(configs);
      const batchResult: BatchImportResult = {
        success_count: result.success_count,
        failed_count: result.failed_count,
        failures: result.failures,
      };
      set({ importStatus: 'success', importResult: batchResult });
      // 批量注册成功后重新加载列表
      await get().loadSkills();
      return batchResult;
    } catch (error) {
      set({
        importStatus: 'error',
        importResult: null,
      });
      throw error;
    }
  },

  updateSkill: async (skillId, config) => {
    try {
      await mcpSkillService.updateSkill(skillId, config);
      await get().loadSkills();
    } catch (error) {
      throw error;
    }
  },

  deleteSkill: async (skillId) => {
    try {
      await mcpSkillService.deleteSkill(skillId);
      set((state) => ({
        skills: state.skills.filter((s) => s.id !== skillId),
      }));
    } catch (error) {
      throw error;
    }
  },

  resetSubmitStatus: () => {
    set({ submitStatus: 'idle', submitError: '' });
  },

  resetImportStatus: () => {
    set({ importStatus: 'idle', importResult: null });
  },
}));
