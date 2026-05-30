/**
 * Luna AI Prompt 服务 API
 * 做什么：封装与 Go Runtime 交互的 Prompt 模板与版本管理 HTTP 请求。
 * 为什么这样做：集中管理 API 请求，提供类型安全的返回值，便于统一错误处理。
 * 边界条件：后端接口未就绪时返回空数组/空值，不抛出 404 异常。
 */
import { PromptTemplate, PromptVersion } from '../types/prompt';
import { ResponseModel } from '../../shared/enum';

const API_BASE = 'http://127.0.0.1:8080/api/v1/prompts';

export const promptService = {
  /**
   * 获取所有 Prompt 模板
   * 后端尚未实现时返回空数组
   */
  getTemplates: async (): Promise<PromptTemplate[]> => {
    const res = await fetch(`${API_BASE}/templates`);
    if (res.status === 404) {
      // 后端接口尚未就绪，返回空列表
      return [];
    }
    if (!res.ok) {
      throw new Error(`获取模板列表失败: ${res.statusText}`);
    }
    const data: ResponseModel<PromptTemplate[]> = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '获取模板列表失败');
    }
    return data.data;
  },

  /**
   * 创建新的 Prompt 模板
   */
  createTemplate: async (
    name: string,
    category: string,
    slotPosition: string,
    isSystem: boolean
  ): Promise<PromptTemplate> => {
    const res = await fetch(`${API_BASE}/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, category, slot_position: slotPosition, is_system: isSystem }),
    });
    if (res.status === 404) {
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) {
      throw new Error(`创建模板失败: ${res.statusText}`);
    }
    const data: ResponseModel<PromptTemplate> = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '创建模板失败');
    }
    return data.data;
  },

  /**
   * 获取指定模板的所有版本历史
   */
  getVersions: async (templateId: string): Promise<PromptVersion[]> => {
    const res = await fetch(`${API_BASE}/templates/${templateId}/versions`);
    if (res.status === 404) {
      return [];
    }
    if (!res.ok) {
      throw new Error(`获取版本历史失败: ${res.statusText}`);
    }
    const data: ResponseModel<PromptVersion[]> = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '获取版本历史失败');
    }
    return data.data;
  },

  /**
   * 为指定模板创建新版本
   */
  createVersion: async (
    templateId: string,
    content: string,
    variables: string
  ): Promise<PromptVersion> => {
    const res = await fetch(`${API_BASE}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId, content, variables }),
    });
    if (res.status === 404) {
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) {
      throw new Error(`创建版本失败: ${res.statusText}`);
    }
    const data: ResponseModel<PromptVersion> = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '创建版本失败');
    }
    return data.data;
  },

  /**
   * 发布指定版本（将其设为模板的 active_version）
   */
  publishVersion: async (templateId: string, versionId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/versions/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId, version_id: versionId }),
    });
    if (res.status === 404) {
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) {
      throw new Error(`发布版本失败: ${res.statusText}`);
    }
    const data: ResponseModel = await res.json();
    if (data.code !== 0) {
      throw new Error(data.msg || '发布版本失败');
    }
  },
};
