/**
 * Luna AI 全局配置状态管理
 * 做什么：管理从 Go Runtime 获取的系统配置状态。
 * 为什么这样做：提供全局可访问的配置状态，并支持通过 WebSocket 监听配置变更实现热更新。
 */
import { create } from 'zustand';
import { SafeConfig } from '../types/config';
import { configService } from '../services/configService';

interface ConfigState {
  /** 当前系统配置（脱敏） */
  config: SafeConfig | null;
  /** 是否正在加载配置 */
  isLoading: boolean;
  /** 加载或更新配置时的错误信息 */
  error: string | null;

  /** 从后端获取最新配置 */
  fetchConfig: () => Promise<void>;
  /** 更新配置到后端 */
  updateConfig: (updates: Record<string, any>) => Promise<void>;
  /** 接收 WebSocket 推送的配置更新 */
  setConfigFromWS: (newConfig: SafeConfig) => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  config: null,
  isLoading: false,
  error: null,

  fetchConfig: async () => {
    set({ isLoading: true, error: null });
    try {
      const data = await configService.getConfig();
      set({ config: data, isLoading: false });
    } catch (err: any) {
      set({ error: err.message || 'Failed to load config', isLoading: false });
    }
  },

  updateConfig: async (updates) => {
    set({ isLoading: true, error: null });
    try {
      await configService.updateConfig(updates);
      // 更新成功后，后端会通过 WS 广播 config.changed 事件，
      // 前端监听到事件后会调用 setConfigFromWS 更新本地状态，
      // 这里也可以选择主动 fetch 一次，但依赖 WS 广播更符合 SSOT 原则。
      set({ isLoading: false });
    } catch (err: any) {
      set({ error: err.message || 'Failed to update config', isLoading: false });
      throw err; // 抛出错误以便 UI 层处理
    }
  },

  setConfigFromWS: (newConfig) => {
    set({ config: newConfig });
  },
}));
