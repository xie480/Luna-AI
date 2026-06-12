// frontend/src/renderer/services/mcpLocalServerService.ts
/**
 * MCP 本地服务器 API Service。
 *
 * 做什么：封装所有本地 MCP 服务器相关的后端 API 调用。
 * 为什么这样做：将 API 调用逻辑从组件中分离，便于复用和单元测试。
 * 输入输出：所有方法返回 Promise，组件通过 async/await 调用。
 * 边界条件：环境变量中的敏感信息（如密码、Token）在前端不做加密处理，
 *           由后端统一加密持久化。
 * 异常行为：网络错误抛出异常，组件层负责错误提示。
 */

import { LocalServerConfig, LocalServerInfo } from '../../shared/types';

const BASE_URL = '/api/v1/mcp/local';

/**
 * 注册本地 MCP 服务器请求体
 */
export interface RegisterLocalServerRequest extends LocalServerConfig {}

/**
 * 注册本地 MCP 服务器响应体
 */
export interface RegisterLocalServerResponse {
  server_id: string;
  success: boolean;
  tool_names: string[];
}

/**
 * 更新本地 MCP 服务器请求体。
 */
export interface UpdateLocalServerRequest {
  name?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  description?: string;
  enabled?: boolean;
}

/**
 * 注册单个本地 MCP 服务器。
 */
export async function registerLocalServer(
  config: RegisterLocalServerRequest
): Promise<RegisterLocalServerResponse> {
  const response = await fetch(BASE_URL + '/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    let errorMsg: string;
    try {
      const errorJson = JSON.parse(errorBody);
      errorMsg = errorJson.detail || errorJson.msg || `HTTP ${response.status}`;
    } catch {
      errorMsg = errorBody || `HTTP ${response.status}`;
    }
    throw new Error(errorMsg);
  }

  return response.json();
}

/**
 * 批量注册本地 MCP 服务器。
 */
export async function batchRegisterLocalServers(
  configs: RegisterLocalServerRequest[]
): Promise<{
  success_count: number;
  failed_count: number;
  failures: Array<{ name: string; error: string }>;
}> {
  const response = await fetch(BASE_URL + '/batch-register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ servers: configs }),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    let errorMsg: string;
    try {
      const errorJson = JSON.parse(errorBody);
      errorMsg = errorJson.detail || errorJson.msg || `HTTP ${response.status}`;
    } catch {
      errorMsg = errorBody || `HTTP ${response.status}`;
    }
    throw new Error(errorMsg);
  }

  return response.json();
}

/**
 * 获取已注册的本地服务器列表。
 */
export async function listLocalServers(): Promise<LocalServerInfo[]> {
  const response = await fetch(BASE_URL + '/servers');

  if (!response.ok) {
    throw new Error(`获取本地服务器列表失败: HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * 更新本地 MCP 服务器配置。
 */
export async function updateLocalServer(
  serverId: string,
  config: UpdateLocalServerRequest
): Promise<{ success: boolean }> {
  const response = await fetch(`${BASE_URL}/servers/${serverId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const errorBody = await response.text();
    let errorMsg: string;
    try {
      const errorJson = JSON.parse(errorBody);
      errorMsg = errorJson.detail || errorJson.msg || `HTTP ${response.status}`;
    } catch {
      errorMsg = errorBody || `HTTP ${response.status}`;
    }
    throw new Error(errorMsg);
  }

  return response.json();
}

/**
 * 删除本地 MCP 服务器。
 */
export async function deleteLocalServer(
  serverId: string
): Promise<{ success: boolean }> {
  const response = await fetch(`${BASE_URL}/servers/${serverId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`删除本地服务器失败: HTTP ${response.status}`);
  }

  return response.json();
}
