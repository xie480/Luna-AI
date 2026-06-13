/**
 * MCP Skill API Service。
 *
 * 做什么：封装所有 MCP Skill 相关的后端 API 调用。
 * 为什么这样做：将 API 调用逻辑从组件中分离，便于复用和单元测试。
 * 输入输出：所有方法返回 Promise，组件通过 async/await 调用。
 * 边界条件：环境变量中的敏感信息在前端不做加密处理，由后端统一加密持久化。
 * 异常行为：网络错误抛出异常，组件层负责错误提示。
 */

import { AI_SERVICE_BASE_URL } from '../appConfig';

/** MCP Skill API 基础 URL */
const BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/mcp/skills`;

/**
 * 后端统一响应包装结构。
 */
interface ApiResponse<T> {
  code: number;
  msg: string;
  data: T;
  trace_id: string;
}

/**
 * Skill 配置（注册/导入用）。
 */
export interface SkillConfig {
  /** Skill 唯一名称。 */
  name: string;
  /** Skill 功能描述。 */
  description?: string;
  /** Skill 版本号。 */
  version?: string;
  /** 是否启用。 */
  enabled?: boolean;
  metadata?: Record<string, any>;
  prompts?: any[];
  resources?: any[];
  tools?: any[];
  servers?: any[];
}

/**
 * Skill 完整信息（从后端获取）。
 */
export interface SkillInfo {
  /** Skill ID。 */
  id: string;
  /** Skill 名称。 */
  name: string;
  /** Skill 描述。 */
  description: string;
  /** 版本号。 */
  version: string;
  /** 是否启用。 */
  enabled: boolean;
  /** 扩展元数据。 */
  metadata: Record<string, unknown>;
  /** 创建时间。 */
  created_at: string;
  /** 更新时间。 */
  updated_at: string;
  
  /** 关联工具 */
  tools?: Array<{
    id: string;
    name: string;
    description: string;
    core_purpose: string;
  }>;
  /** 关联 Prompt */
  prompts?: Array<{
    id: string;
    phase: string;
    content: string;
  }>;
  /** 关联资源 */
  resources?: Array<{
    id: string;
    name: string;
    resource_type: string;
    uri: string;
  }>;
}

/**
 * 注册 Skill 响应。
 */
export interface RegisterSkillResponse {
  skill_id: string;
  success: boolean;
}

/**
 * 更新 Skill 请求体。
 */
export interface UpdateSkillRequest {
  name?: string;
  description?: string;
  version?: string;
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
 * 获取已注册的 Skill 列表。
 */
export async function listSkills(): Promise<SkillInfo[]> {
  return _request<SkillInfo[]>(BASE_URL);
}

/**
 * 获取 MCP Skill 详情（包含 tools, prompts, resources）。
 */
export async function getSkillDetail(skillId: string): Promise<SkillInfo> {
  return _request<SkillInfo>(`${BASE_URL}/${skillId}`);
}

/**
 * 注册单个 MCP Skill。
 */
export async function registerSkill(
  config: SkillConfig
): Promise<RegisterSkillResponse> {
  return _request<RegisterSkillResponse>(BASE_URL + '/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

/**
 * 批量注册 MCP Skill。
 */
export async function batchRegisterSkills(
  configs: SkillConfig[]
): Promise<BatchRegisterData> {
  return _request<BatchRegisterData>(BASE_URL + '/batch-register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skills: configs }),
  });
}

/**
 * 更新 MCP Skill 配置。
 */
export async function updateSkill(
  skillId: string,
  config: UpdateSkillRequest
): Promise<{ success: boolean }> {
  return _request<{ success: boolean }>(`${BASE_URL}/${skillId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

/**
 * 删除 MCP Skill。
 */
export async function deleteSkill(
  skillId: string
): Promise<{ success: boolean }> {
  return _request<{ success: boolean }>(`${BASE_URL}/${skillId}`, {
    method: 'DELETE',
  });
}
