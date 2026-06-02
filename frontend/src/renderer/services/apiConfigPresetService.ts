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
const API_BASE_URL = 'http://localhost:8081/api/v1/config/presets';


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

  async savePreset(preset: Omit<ApiConfigPreset, 'is_active'>): Promise<string> {
    const response = await fetch(API_BASE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(preset),
    });
    if (!response.ok) {
      throw new Error('保存预设失败');
    }
    const result = await response.json();
    if (result.code !== 0) {
      throw new Error(result.msg || '保存预设失败');
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
    const response = await fetch('http://localhost:8081/api/v1/models/fetch', {
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
