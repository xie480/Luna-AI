/**
 * Luna AI 配置服务 API
 * 做什么：封装与 Go Runtime 交互的配置相关 HTTP 请求。
 * 为什么这样做：集中管理 API 请求，提供类型安全的返回值，便于统一错误处理。
 * 边界条件：后端接口未就绪时返回默认值，不抛出 404 异常。
 */
import { SafeConfig } from '../types/config';
import { ResponseModel } from '../../shared/enum';

const API_BASE = 'http://127.0.0.1:8080/api/v1';

export const configService = {
  /**
   * 获取当前系统配置（脱敏）
   * 后端尚未实现时返回默认配置，不抛异常
   */
  getConfig: async (): Promise<SafeConfig> => {
    const res = await fetch(`${API_BASE}/config`);
    if (res.status === 404) {
      // 后端接口尚未就绪，返回默认配置
      return { has_llm_api_key: false };
    }
    if (!res.ok) {
      throw new Error(`获取配置失败: ${res.statusText}`);
    }
    const data: ResponseModel<SafeConfig> = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '获取配置失败');
    }
    return data.data;
  },

  /**
   * 更新系统配置
   * @param updates 要更新的配置项键值对
   */
  updateConfig: async (updates: Record<string, any>): Promise<void> => {
    const res = await fetch(`${API_BASE}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (res.status === 404) {
      // 后端接口尚未就绪，静默忽略
      return;
    }
    if (!res.ok) {
      throw new Error(`更新配置失败: ${res.statusText}`);
    }
    const data: ResponseModel = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '更新配置失败');
    }
  },
};
