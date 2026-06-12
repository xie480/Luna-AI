// frontend/src/renderer/stores/mcpLocalServerStore.ts
/**
 * MCP 本地服务器状态 Store。
 *
 * 做什么：管理 MCP 本地服务器面板的全局状态。
 * 为什么这样做：本地服务器列表需要跨组件共享（列表组件、编辑弹窗、状态指示器）。
 * 边界条件：组件卸载时不重置状态，由面板生命周期管理。
 * 异常行为：后端查询失败时保持上次成功加载的缓存。
 */

import { create } from 'zustand';
import type { LocalServerInfo, BatchImportResult } from '../../shared/types';
import * as mcpLocalServerService from '../services/mcpLocalServerService';

/**
 * 本地服务器 Store 状态和动作接口。
 */
interface LocalServerStoreState {
  /** 已注册的本地服务器列表。 */
  servers: LocalServerInfo[];
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

  /** 加载本地服务器列表。 */
  loadServers: () => Promise<void>;
  /** 注册单个本地服务器。 */
  registerServer: (config: mcpLocalServerService.RegisterLocalServerRequest) => Promise<void>;
  /** 批量注册本地服务器。 */
  batchRegisterServers: (configs: mcpLocalServerService.RegisterLocalServerRequest[]) => Promise<BatchImportResult>;
  /** 更新本地服务器配置。 */
  updateServer: (serverId: string, config: mcpLocalServerService.UpdateLocalServerRequest) => Promise<void>;
  /** 删除本地服务器。 */
  deleteServer: (serverId: string) => Promise<void>;
  /** 重置提交状态。 */
  resetSubmitStatus: () => void;
  /** 重置导入状态。 */
  resetImportStatus: () => void;
}

export const useLocalServerStore = create<LocalServerStoreState>((set, get) => ({
  servers: [],
  isLoading: false,
  loadError: '',
  submitStatus: 'idle',
  submitError: '',
  importStatus: 'idle',
  importResult: null,

  loadServers: async () => {
    set({ isLoading: true, loadError: '' });
    try {
      const servers = await mcpLocalServerService.listLocalServers();
      set({ servers, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        loadError: error instanceof Error ? error.message : '加载本地服务器列表失败',
      });
    }
  },

  registerServer: async (config) => {
    set({ submitStatus: 'submitting', submitError: '' });
    try {
      await mcpLocalServerService.registerLocalServer(config);
      set({ submitStatus: 'success' });
      // 注册成功后重新加载列表
      await get().loadServers();
    } catch (error) {
      set({
        submitStatus: 'error',
        submitError: error instanceof Error ? error.message : '注册失败',
      });
      throw error; // 让调用方也能捕获错误
    }
  },

  batchRegisterServers: async (configs) => {
    set({ importStatus: 'importing', importResult: null });
    try {
      const result = await mcpLocalServerService.batchRegisterLocalServers(configs);
      set({ importStatus: 'success', importResult: result });
      // 批量注册成功后重新加载列表
      await get().loadServers();
      return result;
    } catch (error) {
      set({
        importStatus: 'error',
        importResult: null,
      });
      throw error;
    }
  },

  updateServer: async (serverId, config) => {
    try {
      await mcpLocalServerService.updateLocalServer(serverId, config);
      await get().loadServers();
    } catch (error) {
      throw error;
    }
  },

  deleteServer: async (serverId) => {
    try {
      await mcpLocalServerService.deleteLocalServer(serverId);
      set((state) => ({
        servers: state.servers.filter((s) => s.id !== serverId),
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
