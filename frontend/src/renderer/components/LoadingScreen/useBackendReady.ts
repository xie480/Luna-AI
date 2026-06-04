import { useState, useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { checkBackendReady } from '../../services/healthService';

/**
 * 监听后端服务是否已经完全就绪。
 * 只有在 `isBackendReady` 为 true 且
 * 最小加载时间已到达时返回 true，确保加载动画拥有足够的观赏时间。
 */
export const useBackendReady = (minLoadingTimeMs = 2000) => {
  const [ready, setReady] = useState(false);
  const [timeElapsed, setTimeElapsed] = useState(false);

  const isBackendReady = useSystemStore((state) => state.isBackendReady);

  // 确保加载动画至少展示指定时长
  useEffect(() => {
    const timer = setTimeout(() => setTimeElapsed(true), minLoadingTimeMs);
    return () => clearTimeout(timer);
  }, [minLoadingTimeMs]);

  // 轮询 health 接口作为兜底，防止 SSE 事件丢失
  useEffect(() => {
    if (isBackendReady) return;

    const checkHealth = async () => {
      try {
        const available = await checkBackendReady();
        if (available) {
          useSystemStore.getState().setBackendReady(true);
        }
      } catch (e) {
        // ignore
      }
    };

    const interval = setInterval(checkHealth, 2000);
    checkHealth(); // 立即执行一次

    return () => clearInterval(interval);
  }, [isBackendReady]);

  // 当后端状态满足且时间已到达时标记就绪
  useEffect(() => {
    if (isBackendReady && timeElapsed) {
      setReady(true);
    }
  }, [isBackendReady, timeElapsed]);

  return ready;
};
