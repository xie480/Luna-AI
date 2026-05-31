import { create } from 'zustand';
import { apiConfigPresetService, ApiConfigPreset } from '../services/apiConfigPresetService';

interface ApiConfigPresetState {
  presets: ApiConfigPreset[];
  activePresetId: string | null;
  isLoading: boolean;
  error: string | null;

  // 获取所有预设
  fetchPresets: () => Promise<void>;
  // 保存预设
  savePreset: (preset: Omit<ApiConfigPreset, 'is_active'>) => Promise<string>;
  // 激活预设
  activatePreset: (id: string) => Promise<void>;
  // 删除预设
  deletePreset: (id: string) => Promise<void>;
  // 动态获取模型列表
  fetchModels: (baseUrl: string, apiKey: string) => Promise<{ id: string; name: string }[]>;
}

export const useApiConfigPresetStore = create<ApiConfigPresetState>((set, get) => ({
  presets: [],
  activePresetId: null,
  isLoading: false,
  error: null,

  fetchPresets: async () => {
    set({ isLoading: true, error: null });
    try {
      const presets = await apiConfigPresetService.getPresets();
      const activePreset = presets.find(p => p.is_active);
      set({
        presets,
        activePresetId: activePreset ? activePreset.id : null,
        isLoading: false
      });
    } catch (error: unknown) {
      const err = error as Error;
      set({ error: err.message || '获取预设列表失败', isLoading: false });
    }
  },

  savePreset: async (preset) => {
    set({ isLoading: true, error: null });
    try {
      const id = await apiConfigPresetService.savePreset(preset);
      await get().fetchPresets(); // 重新加载列表
      return id;
    } catch (error: unknown) {
      const err = error as Error;
      set({ error: err.message || '保存预设失败', isLoading: false });
      throw error;
    }
  },

  activatePreset: async (id) => {
    set({ isLoading: true, error: null });
    try {
      await apiConfigPresetService.activatePreset(id);
      await get().fetchPresets(); // 重新加载列表以更新激活状态
    } catch (error: unknown) {
      const err = error as Error;
      set({ error: err.message || '激活预设失败', isLoading: false });
      throw error;
    }
  },

  deletePreset: async (id) => {
    set({ isLoading: true, error: null });
    try {
      await apiConfigPresetService.deletePreset(id);
      await get().fetchPresets(); // 重新加载列表
    } catch (error: unknown) {
      const err = error as Error;
      set({ error: err.message || '删除预设失败', isLoading: false });
      throw error;
    }
  },

  fetchModels: async (baseUrl, apiKey) => {
    return await apiConfigPresetService.fetchModels(baseUrl, apiKey);
  }
}));
