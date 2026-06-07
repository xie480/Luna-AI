/**
 * Luna AI API 配置预设服务
 *
 * 做什么：封装 API 配置预设的 CRUD 操作，与后端 HTTP API 交互。
 * 为什么这样做：统一管理预配置记录，支持多预设切换和模型列表动态获取。
 */
import { AI_SERVICE_BASE_URL } from '../appConfig';

export interface ModelConfig {
  base_url: string;
  api_key: string;
  model_id: string;
  max_tokens: number;
  max_context_tokens: number;
  temperature: number;
}

export interface ApiConfigPreset {
  id: string;
  name: string;
  is_active: boolean;
  large_model_config: ModelConfig;
  medium_model_config: ModelConfig;
  small_model_config: ModelConfig;
}

/** API 配置预设基础 URL（端口从 .env 文件统一读取） */
const API_BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/config/presets`;
/** 模型列表接口 URL（端口从 .env 文件统一读取） */
const MODELS_API_URL = `${AI_SERVICE_BASE_URL}/api/v1/config/presets/fetch-models`;


export const apiConfigPresetService = {
  async getPresets(): Promise<ApiConfigPreset[]> {
    const response = await fetch(API_BASE_URL);
    if (!response.ok) {
      throw new Error('获取预设列表失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '获取预设列表失败');
    }
    return result.data || [];
  },

  async createPreset(preset: Omit<ApiConfigPreset, 'is_active'>): Promise<string> {
    const response = await fetch(API_BASE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(preset),
    });
    if (!response.ok) {
      throw new Error('创建预设失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '创建预设失败');
    }
    return result.data.id;
  },

  async updatePreset(preset: Omit<ApiConfigPreset, 'is_active'>): Promise<string> {
    // 发送 PUT 请求时去除 id 字段，避免与路径参数冲突（后端 UpdatePresetRequest 不含 id）
    const { id, ...updateBody } = preset;
    const response = await fetch(`${API_BASE_URL}/${id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(updateBody),
    });
    if (!response.ok) {
      // 尝试获取 422 错误详情以便排查
      let detail = '';
      try {
        const errBody = await response.json();
        detail = JSON.stringify(errBody);
      } catch {
        detail = response.statusText;
      }
      throw new Error(`更新预设失败 (${response.status}): ${detail}`);
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '更新预设失败');
    }
    return result.data.id;
  },

  async activatePreset(id: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/${id}/activate`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('激活预设失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '激活预设失败');
    }
  },

  async deletePreset(id: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/${id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error('删除预设失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '删除预设失败');
    }
  },

  async fetchModels(baseUrl: string, apiKey: string): Promise<{ id: string; name: string }[]> {
    const response = await fetch(MODELS_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
    });
    if (!response.ok) {
      throw new Error('获取模型列表失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '获取模型列表失败');
    }
    return result.data || [];
  }
};
