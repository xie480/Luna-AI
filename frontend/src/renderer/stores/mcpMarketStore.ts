/**
 * MCP 市场状态管理 Store。
 *
 * 做什么：管理 MCP 市场相关的全部前端状态，包括市场列表、已接入实例、
 *         详情缓存和搜索状态。
 * 为什么这样做：MCP 市场涉及浏览、搜索、接入、管理等多个交互场景，
 *              需要独立的状态管理层。
 * 输入输出：状态通过后端 API 查询获取，前端只做缓存和展示。
 * 边界条件：
 *   - 市场列表刷新时不应丢失当前已接入实例的状态。
 *   - 接入操作时使用乐观更新，但失败时需要回滚。
 */
import { create } from 'zustand';
import { mcpMarketService } from '../services/mcpMarketService';
import type {
  MCPMarketItem,
  MCPMarketDetail,
  MCPInstalledInstance,
  InstallConfig,
} from '../types/mcpMarket';

/**
 * MCP 市场 Store 状态接口。
 */
interface MCPMarketState {
  // === 市场浏览 ===
  /** 市场列表条目（分页加载）。 */
  marketItems: MCPMarketItem[];
  /** 市场列表总数。 */
  marketTotal: number;
  /** 当前浏览页码。 */
  marketPage: number;
  /** 当前搜索关键词。 */
  marketSearchQuery: string;
  /** 是否正在加载市场列表。 */
  isMarketLoading: boolean;

  // === 市场详情 ===
  /** 当前查看的条目详情。 */
  currentDetail: MCPMarketDetail | null;
  /** 是否正在加载详情。 */
  isDetailLoading: boolean;

  // === 已接入实例 ===
  /** 已接入的远程 MCP 实例列表。 */
  installedInstances: MCPInstalledInstance[];
  /** 是否正在加载已接入列表。 */
  isInstancesLoading: boolean;

  // === 接入操作 ===
  /** 当前正在接入的 marketplace_id（用于按钮 loading 状态）。 */
  installingMarketplaceId: string | null;
  /** 接入操作是否成功（用于反馈提示）。 */
  installResult: { success: boolean; message: string } | null;

  // === 错误状态 ===
  /** 市场列表加载错误信息。 */
  marketError: string | null;
  /** 详情加载错误信息。 */
  detailError: string | null;

  // === Actions ===
  /** 获取市场列表（分页）。 */
  fetchMarketList: (page?: number) => Promise<void>;
  /** 搜索市场。 */
  searchMarket: (query: string) => Promise<void>;
  /** 获取市场条目详情。 */
  fetchMarketDetail: (id: string) => Promise<void>;
  /** 获取已接入实例列表。 */
  fetchInstalledInstances: () => Promise<void>;
  /** 一键接入远程 MCP。 */
  installRemoteMCP: (marketplaceId: string, config: InstallConfig) => Promise<void>;
  /** 卸载已接入的远程 MCP。 */
  uninstallRemoteMCP: (instanceId: string) => Promise<void>;
  /** 切换实例启用/禁用。 */
  toggleInstanceActive: (instanceId: string, active: boolean) => Promise<void>;
  /** 手动触发健康检查。 */
  triggerHealthCheck: (instanceId: string) => Promise<void>;
  /** 清除接入结果反馈。 */
  clearInstallResult: () => void;
  /** 清除错误状态。 */
  clearErrors: () => void;
}

/** Store 初始默认值。 */
const initialMarketState: Partial<MCPMarketState> = {
  marketItems: [],
  marketTotal: 0,
  marketPage: 1,
  marketSearchQuery: '',
  isMarketLoading: false,
  currentDetail: null,
  isDetailLoading: false,
  installedInstances: [],
  isInstancesLoading: false,
  installingMarketplaceId: null,
  installResult: null,
  marketError: null,
  detailError: null,
};

/**
 * MCP 市场 Zustand Store。
 */
export const useMCPMarketStore = create<MCPMarketState>((set, get) => ({
  ...initialMarketState as MCPMarketState,

  fetchMarketList: async (page = 1) => {
    set({ isMarketLoading: true, marketPage: page, marketError: null });
    try {
      const result = await mcpMarketService.listMarketplace({
        page,
        sort_by: 'trust_score',
      });
      set({
        marketItems: result.items,
        marketTotal: result.total,
        isMarketLoading: false,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取市场列表失败';
      set({ isMarketLoading: false, marketError: message });
    }
  },

  searchMarket: async (query: string) => {
    set({ isMarketLoading: true, marketSearchQuery: query, marketError: null });
    try {
      const result = await mcpMarketService.searchMarketplace(query);
      set({
        marketItems: result.items,
        marketTotal: result.total,
        isMarketLoading: false,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '搜索失败';
      set({ isMarketLoading: false, marketError: message });
    }
  },

  fetchMarketDetail: async (id: string) => {
    set({ isDetailLoading: true, detailError: null });
    try {
      const detail = await mcpMarketService.getMarketDetail(id);
      set({ currentDetail: detail, isDetailLoading: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取详情失败';
      set({ isDetailLoading: false, detailError: message });
    }
  },

  fetchInstalledInstances: async () => {
    set({ isInstancesLoading: true });
    try {
      const instances = await mcpMarketService.getInstalledInstances();
      set({ installedInstances: instances, isInstancesLoading: false });
    } catch {
      set({ isInstancesLoading: false });
    }
  },

  installRemoteMCP: async (marketplaceId: string, config: InstallConfig) => {
    set({ installingMarketplaceId: marketplaceId, installResult: null });
    try {
      const result = await mcpMarketService.installRemoteMCP(marketplaceId, config);
      // 刷新已接入列表
      await get().fetchInstalledInstances();
      set({
        installingMarketplaceId: null,
        installResult: {
          success: true,
          message: `已成功接入 ${result.tool_count} 个工具`,
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '接入失败';
      set({
        installingMarketplaceId: null,
        installResult: { success: false, message: `接入失败: ${message}` },
      });
    }
  },

  uninstallRemoteMCP: async (instanceId: string) => {
    try {
      await mcpMarketService.uninstallRemoteMCP(instanceId);
      await get().fetchInstalledInstances();
    } catch {
      // 错误由调用方处理
    }
  },

  toggleInstanceActive: async (instanceId: string, active: boolean) => {
    try {
      await mcpMarketService.toggleInstanceActive(instanceId, active);
      await get().fetchInstalledInstances();
    } catch {
      // 错误由调用方处理
    }
  },

  triggerHealthCheck: async (instanceId: string) => {
    try {
      await mcpMarketService.triggerHealthCheck(instanceId);
    } catch {
      // 错误由调用方处理
    }
  },

  clearInstallResult: () => set({ installResult: null }),

  clearErrors: () => set({ marketError: null, detailError: null }),
}));
