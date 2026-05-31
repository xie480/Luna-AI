/**
 * Luna AI Prompt 服务 API
 * 做什么：封装与 Go Runtime 交互的 Prompt 模板与版本管理 HTTP 请求。
 * 为什么这样做：使用后端端点自探测机制避免重复 404 网络报错。
 * 首次探测到 404 后会缓存不可用状态，后续请求不再发起网络调用。
 */
import { PromptTemplate, PromptVersion } from '../types/prompt';
import { ResponseModel } from '../../shared/enum';

const API_BASE = 'http://127.0.0.1:8080/api/v1/prompts';

/** 后端端点可用性缓存：null=未探测, true=可用, false=不可用 */
let _isPromptsReady: boolean | null = null;
/** 探测 Promise 队列，防止并发探测 */
let _probePromise: Promise<boolean> | null = null;

/**
 * 探测 /templates 端点是否可用
 * 首次调用时发起真实请求，后续只返回缓存值
 */
async function probePromptsEndpoint(): Promise<boolean> {
  if (_isPromptsReady !== null) return _isPromptsReady;
  if (_probePromise) return _probePromise;

  _probePromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/templates`);
      _isPromptsReady = res.ok;
      return _isPromptsReady;
    } catch {
      _isPromptsReady = false;
      return false;
    } finally {
      _probePromise = null;
    }
  })();

  return _probePromise;
}

/** 重置可用性缓存（WebSocket 重连时调用） */
export function resetPromptsProbe(): void {
  _isPromptsReady = null;
}

export const promptService = {
  /**
   * 获取所有 Prompt 模板
   * 后端尚未实现时返回空数组，仅首次探测产生一次 404 日志
   */
  getTemplates: async (): Promise<PromptTemplate[]> => {
    const ready = await probePromptsEndpoint();
    if (!ready) {
      return [];
    }

    const res = await fetch(`${API_BASE}/templates`);
    if (res.status === 404) {
      _isPromptsReady = false;
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

  /** 创建新的 Prompt 模板 */
  createTemplate: async (
    name: string,
    category: string,
    slotPosition: string,
    isSystem: boolean
  ): Promise<PromptTemplate> => {
    const ready = await probePromptsEndpoint();
    if (!ready) throw new Error('后端 Prompt 管理接口尚未就绪');

    const res = await fetch(`${API_BASE}/templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, category, slot_position: slotPosition, is_system: isSystem }),
    });
    if (res.status === 404) {
      _isPromptsReady = false;
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) throw new Error(`创建模板失败: ${res.statusText}`);
    const data: ResponseModel<PromptTemplate> = await res.json();
    if (data.code !== 0) throw new Error(data.msg || '创建模板失败');
    return data.data;
  },

  /**
   * 获取指定模板的所有版本历史
   */
  getVersions: async (templateId: string): Promise<PromptVersion[]> => {
    const ready = await probePromptsEndpoint();
    if (!ready) return [];

    const res = await fetch(`${API_BASE}/templates/${templateId}/versions`);
    if (res.status === 404) return [];
    if (!res.ok) throw new Error(`获取版本历史失败: ${res.statusText}`);
    const data: ResponseModel<PromptVersion[]> = await res.json();
    if (data.code !== 0) throw new Error(data.msg || '获取版本历史失败');
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
    const ready = await probePromptsEndpoint();
    if (!ready) throw new Error('后端 Prompt 管理接口尚未就绪');

    const res = await fetch(`${API_BASE}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId, content, variables }),
    });
    if (res.status === 404) {
      _isPromptsReady = false;
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) throw new Error(`创建版本失败: ${res.statusText}`);
    const data: ResponseModel<PromptVersion> = await res.json();
    if (data.code !== 0) throw new Error(data.msg || '创建版本失败');
    return data.data;
  },

  /**
   * 发布指定版本
   */
  publishVersion: async (templateId: string, versionId: string): Promise<void> => {
    const ready = await probePromptsEndpoint();
    if (!ready) throw new Error('后端 Prompt 管理接口尚未就绪');

    const res = await fetch(`${API_BASE}/versions/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId, version_id: versionId }),
    });
    if (res.status === 404) {
      _isPromptsReady = false;
      throw new Error('后端 Prompt 管理接口尚未就绪');
    }
    if (!res.ok) throw new Error(`发布版本失败: ${res.statusText}`);
    const data: ResponseModel = await res.json();
    if (data.code !== 0) throw new Error(data.msg || '发布版本失败');
  },
};
