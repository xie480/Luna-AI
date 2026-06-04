/**
 * 后端健康检查服务
 * 做什么：通过 /health 端点检测 Go Runtime 后端是否可用，缓存结果降低网络开销。
 * 为什么这样做：避免前端每个服务层组件都发起独立探测，减少 404 网络请求报错。
 */
let _backendAvailable: boolean | null = null;
let _checkPromise: Promise<boolean> | null = null;

import { HEALTH_URL } from '../appConfig';

/**
 * 检查后端是否可用
 * 使用健康检查端点探测后端，结果缓存在闭包中。
 * 首次调用会发起网络请求，后续直接返回缓存值。
 * 当 SSE 重连成功时，应通过 resetBackendAvailable() 重置缓存。
 */
export async function isBackendAvailable(): Promise<boolean> {
  // 已有缓存结果，直接返回
  if (_backendAvailable !== null) {
    return _backendAvailable;
  }

  // 已有正在进行的探测请求，复用 Promise 防止并发
  if (_checkPromise !== null) {
    return _checkPromise;
  }

  // 发起健康检查请求
  _checkPromise = (async () => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);

      const res = await fetch(HEALTH_URL, {
        method: 'GET',
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        _backendAvailable = data.payload?.status === 'ready';
      } else {
        _backendAvailable = false;
      }
      return _backendAvailable;
    } catch {
      // 网络错误或超时，标记为不可用
      _backendAvailable = false;
      return false;
    } finally {
      _checkPromise = null;
    }
  })();

  return _checkPromise;
}

/**
 * 检查后端是否完全就绪（不使用缓存，用于轮询）
 */
export async function checkBackendReady(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);

    const res = await fetch(HEALTH_URL, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      const isReady = data.payload?.status === 'ready';
      if (isReady) {
        _backendAvailable = true;
      }
      return isReady;
    }
    return false;
  } catch {
    return false;
  }
}

/**
 * 重置后端可用性缓存
 * 当 SSE 连接成功或重连时调用，允许重新探测后端状态
 */
export function resetBackendAvailable(): void {
  _backendAvailable = null;
}
