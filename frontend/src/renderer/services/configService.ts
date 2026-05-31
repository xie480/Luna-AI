/**
 * Luna AI 配置服务 API
 * 做什么：封装与 Go Runtime 交互的配置相关 HTTP 请求。
 * 为什么这样做：集中管理 API 请求，使用后端端点自探测机制避免重复 404 网络报错。
 */
import { SafeConfig } from '../types/config';
import { ResponseModel } from '../../shared/enum';

const API_BASE = 'http://127.0.0.1:8080/api/v1';

/** 后端端点可用性缓存：null=未探测, true=可用, false=不可用 */
let _isConfigReady: boolean | null = null;
/** 是否正在探测中 */
let _probing = false;
/** 探测 Promise 队列，防止并发探测 */
let _probePromise: Promise<boolean> | null = null;

/**
 * 探测 /config 端点是否可用
 * 首次调用时发起真实请求，后续只返回缓存值
 */
async function probeConfigEndpoint(): Promise<boolean> {
  if (_isConfigReady !== null) return _isConfigReady;
  if (_probePromise) return _probePromise;

  _probing = true;
  _probePromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/config`);
      _isConfigReady = res.ok || res.status !== 404;
      return _isConfigReady;
    } catch {
      _isConfigReady = false;
      return false;
    } finally {
      _probing = false;
      _probePromise = null;
    }
  })();

  return _probePromise;
}

/** 重置可用性缓存（WebSocket 重连时调用） */
export function resetConfigProbe(): void {
  _isConfigReady = null;
}

export const configService = {
  /**
   * 获取当前系统配置（脱敏）
   * 后端尚未实现时返回默认配置，不产生 404 网络日志
   */
  getConfig: async (): Promise<SafeConfig> => {
    const ready = await probeConfigEndpoint();
    if (!ready) {
      return { has_llm_api_key: false };
    }

    const res = await fetch(`${API_BASE}/config`);
    if (res.status === 404) {
      _isConfigReady = false; // 更新缓存
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
   */
  updateConfig: async (updates: Record<string, any>): Promise<void> => {
    const ready = await probeConfigEndpoint();
    if (!ready) return;

    const res = await fetch(`${API_BASE}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (res.status === 404) {
      _isConfigReady = false;
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
