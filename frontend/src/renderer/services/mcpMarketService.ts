/**
 * MCP 市场 API 服务。
 *
 * 做什么：封装 MCP 市场相关的所有后端 API 调用。
 * 为什么这样做：前端通过统一的服务层访问后端市场接口，不与 API 路由耦合。
 * 输入输出：所有方法返回 Promise，异常由调用方处理。
 * 边界条件：网络异常时由全局 error handler 拦截，调用方无需重复 try-catch。
 */
import { AI_SERVICE_BASE_URL } from '../appConfig';
import type {
  MCPMarketDetail,
  MCPInstalledInstance,
  InstallConfig,
  InstallResponse,
  MarketplaceListResponse,
} from '../types/mcpMarket';

/** MCP 市场 API 基础 URL。 */
const API_BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/mcp/market`;

/**
 * 通用 HTTP GET 请求。
 */
async function httpGet<T>(url: string): Promise<{ data: T }> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  const result = await response.json();
  if (result.code !== 0) {
    throw new Error(result.msg || '请求失败');
  }
  return { data: result.data as T };
}

/**
 * 通用 HTTP POST 请求。
 */
async function httpPost<T>(url: string, body?: unknown): Promise<{ data: T }> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  const result = await response.json();
  if (result.code !== 0) {
    throw new Error(result.msg || '请求失败');
  }
  return { data: result.data as T };
}

export const mcpMarketService = {
  /**
   * 获取 MCP 市场列表（分页）。
   */
  async listMarketplace(params: {
    page?: number;
    page_size?: number;
    category?: string;
    tag?: string;
    health_status?: string;
    sort_by?: string;
    sort_order?: string;
  }): Promise<MarketplaceListResponse> {
    const query = new URLSearchParams();
    if (params.page) query.set('page', String(params.page));
    query.set('page_size', String(params.page_size || 20));
    if (params.category) query.set('category', params.category);
    if (params.sort_by) query.set('sort_by', params.sort_by);

    const response = await httpGet<MarketplaceListResponse>(
      `${API_BASE_URL}/list?${query.toString()}`,
    );
    return response.data;
  },

  /**
   * 获取市场条目详情。
   */
  async getMarketDetail(id: string): Promise<MCPMarketDetail> {
    const response = await httpGet<MCPMarketDetail>(`${API_BASE_URL}/detail/${id}`);
    return response.data;
  },

  /**
   * 搜索 MCP 市场（支持能力级语义搜索）。
   */
  async searchMarketplace(
    query: string,
    page: number = 1,
  ): Promise<MarketplaceListResponse> {
    const encoded = encodeURIComponent(query);
    const response = await httpGet<MarketplaceListResponse>(
      `${API_BASE_URL}/search?q=${encoded}&page=${page}&page_size=20`,
    );
    return response.data;
  },

  /**
   * 一键接入远程 MCP。
   */
  async installRemoteMCP(
    marketplaceId: string,
    config: InstallConfig,
  ): Promise<InstallResponse> {
    const response = await httpPost<InstallResponse>(
      `${API_BASE_URL}/install/${marketplaceId}`,
      config,
    );
    return response.data;
  },

  /**
   * 卸载已接入的远程 MCP。
   */
  async uninstallRemoteMCP(instanceId: string): Promise<void> {
    await httpPost<void>(`${API_BASE_URL}/uninstall/${instanceId}`);
  },

  /**
   * 获取已接入的远程 MCP 列表。
   */
  async getInstalledInstances(): Promise<MCPInstalledInstance[]> {
    const response = await httpGet<MCPInstalledInstance[]>(
      `${API_BASE_URL}/installed`,
    );
    return response.data;
  },

  /**
   * 更新实例配置。
   */
  async updateInstance(
    instanceId: string,
    config: Partial<InstallConfig>,
  ): Promise<void> {
    await httpPost<void>(`${API_BASE_URL}/instance/${instanceId}`, config);
  },

  /**
   * 切换实例启用/禁用。
   */
  async toggleInstanceActive(
    instanceId: string,
    active: boolean,
  ): Promise<void> {
    await httpPost<void>(`${API_BASE_URL}/instance/${instanceId}/toggle`, {
      active,
    });
  },

  /**
   * 手动触发健康检查。
   */
  async triggerHealthCheck(instanceId: string): Promise<void> {
    await httpPost<void>(`${API_BASE_URL}/instance/${instanceId}/check`);
  },
};
