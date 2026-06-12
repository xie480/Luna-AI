/**
 * MCP 工具配置 API Service。
 *
 * 做什么：封装所有 MCP 工具配置相关的后端 API 调用。
 *         前端在 Skill 面板中展开技能详情，查看工具列表时，
 *         每个工具条目旁有"配置"按钮，点击后弹出配置对话框。
 * 为什么这样做：将 API 调用逻辑从组件中分离，便于复用和单元测试。
 * 输入输出：所有方法返回 Promise，组件通过 async/await 调用。
 */
import { AI_SERVICE_BASE_URL } from '../appConfig';

/** MCP 工具配置 API 基础 URL */
const BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/mcp/tool-configs`;

/** 后端统一响应包装结构。 */
interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T;
  trace_id: string;
}

/** 工具配置对象。 */
export interface ToolConfig {
  tool_name: string;
  config_data: Record<string, unknown>;
  status: string;
  description: string;
  created_at?: string;
  updated_at?: string;
}

/** 配置字段定义（用于前端动态渲染配置表单）。 */
export interface ToolConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'boolean' | 'password';
  required: boolean;
  default?: string;
  placeholder?: string;
  description?: string;
}

/** 工具配置 Schema。 */
export interface ToolConfigSchema {
  title: string;
  description: string;
  fields: ToolConfigField[];
}

/** 获取工具配置及 Schema 的响应。 */
interface GetConfigResponse {
  config: ToolConfig | null;
  schema: ToolConfigSchema | null;
}

/** 保存配置的请求体。 */
interface SaveConfigRequest {
  config_data: Record<string, unknown>;
  description?: string;
}

/**
 * 发起 API 请求并自动解包 data 字段。
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
 * 获取指定工具的配置及字段 Schema。
 * @param toolName 工具名称，如 "web_search"
 */
export async function getToolConfig(
  toolName: string
): Promise<GetConfigResponse> {
  return _request<GetConfigResponse>(`${BASE_URL}/${toolName}`);
}

/**
 * 获取指定工具的配置字段 Schema（不含配置数据）。
 * @param toolName 工具名称
 */
export async function getToolConfigSchema(
  toolName: string
): Promise<ToolConfigSchema | null> {
  return _request<ToolConfigSchema | null>(`${BASE_URL}/${toolName}/schema`);
}

/**
 * 保存工具配置。
 * @param toolName 工具名称
 * @param configData 配置键值对
 * @param description 配置说明（可选）
 */
export async function saveToolConfig(
  toolName: string,
  configData: Record<string, unknown>,
  description?: string
): Promise<{ success: boolean }> {
  const body: SaveConfigRequest = { config_data: configData };
  if (description !== undefined) {
    body.description = description;
  }
  return _request<{ success: boolean }>(`${BASE_URL}/${toolName}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * 删除（软删除）工具配置。
 * @param toolName 工具名称
 */
export async function deleteToolConfig(
  toolName: string
): Promise<{ success: boolean }> {
  return _request<{ success: boolean }>(`${BASE_URL}/${toolName}`, {
    method: 'DELETE',
  });
}
