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

import { AI_SERVICE_BASE_URL } from '../appConfig';
import { LocalServerConfig, LocalServerInfo } from '../../shared/types';

/** MCP 本地服务器 API 基础 URL（端口从 .env 文件统一读取） */
const BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/mcp/local`;

/**
 * 后端统一响应包装结构。
 * 所有后端 API 均返回 { code, msg, data, trace_id } 格式。
 */
interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T;
  trace_id: string;
}

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
 * 批量注册响应 data 结构。
 */
interface BatchRegisterData {
  success_count: number;
  failed_count: number;
  failures: Array<{ name: string; error: string }>;
}

/**
 * 更新/删除响应 data 结构。
 */
interface MutateResponseData {
  success: boolean;
}

/**
 * 发起 API 请求并自动解包 data 字段。
 *
 * 做什么：统一处理 fetch 调用、错误检测、JSON 解析和 data 字段提取。
 * 为什么这样做：所有后端 API 返回统一包装格式 { code, msg, data, trace_id }，
 *              前端只需关注 data 内的业务内容。
 */
async function _request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);

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

  const json: ApiResponse<T> = await response.json();
  if (json.code !== 0) {
    throw new Error(json.msg || '后端返回非零错误码');
  }
  return json.data;
}

/**
 * 注册单个本地 MCP 服务器。
 */
export async function registerLocalServer(
  config: RegisterLocalServerRequest
): Promise<RegisterLocalServerResponse> {
  return _request<RegisterLocalServerResponse>(BASE_URL + '/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

/**
 * 批量注册本地 MCP 服务器。
 */
export async function batchRegisterLocalServers(
  configs: RegisterLocalServerRequest[]
): Promise<BatchRegisterData> {
  return _request<BatchRegisterData>(BASE_URL + '/batch-register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ servers: configs }),
  });
}

/**
 * 获取已注册的本地服务器列表。
 */
export async function listLocalServers(): Promise<LocalServerInfo[]> {
  return _request<LocalServerInfo[]>(BASE_URL + '/servers');
}

/**
 * 更新本地 MCP 服务器配置。
 */
export async function updateLocalServer(
  serverId: string,
  config: UpdateLocalServerRequest
): Promise<MutateResponseData> {
  return _request<MutateResponseData>(`${BASE_URL}/servers/${serverId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

/**
 * 删除本地 MCP 服务器。
 */
export async function deleteLocalServer(
  serverId: string
): Promise<MutateResponseData> {
  return _request<MutateResponseData>(`${BASE_URL}/servers/${serverId}`, {
    method: 'DELETE',
  });
}
