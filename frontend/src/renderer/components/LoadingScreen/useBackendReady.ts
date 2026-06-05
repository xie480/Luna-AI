/**
 * 监听后端 AI 服务是否已经完全就绪。
 * 
 * 做什么：通过独立轮询 /ready 端点判断后端是否完成所有核心初始化并已输出
 *        "Luna AI Service 所有核心资源初始化完成，服务已就绪" 和
 *        "Application startup complete." 日志。
 * 
 * 为什么这样做：
 *   - 与 SSE connected 事件解耦：SSE connected 事件可能携带 is_ready=true
 *     导致加载动画被过早触发，而目标日志尚未输出。
 *   - /ready 端点只有在 FastAPI lifespan yield 之后才对外响应，此时上述两条
 *     日志已被输出，确保加载动画时序正确。
 * 
 * 仅在 isBackendReady 为 true 且最小加载时间已到达时返回 true，
 * 确保加载动画拥有足够的观赏时间。
 */
import { useState, useEffect } from 'react';
import { checkServiceReady } from '../../services/healthService';

export const useBackendReady = (minLoadingTimeMs = 2500) => {
  const [ready, setReady] = useState(false);
  const [timeElapsed, setTimeElapsed] = useState(false);
  const [serviceReady, setServiceReady] = useState(false);

  // 确保加载动画至少展示指定时长
  useEffect(() => {
    const timer = setTimeout(() => setTimeElapsed(true), minLoadingTimeMs);
    return () => clearTimeout(timer);
  }, [minLoadingTimeMs]);

  // 独立轮询 /ready 端点，判断 AI 服务是否完全就绪
  // 不受 SSE connected 事件干扰
  useEffect(() => {
    if (serviceReady) return;

    let cancelled = false;

    const checkReady = async () => {
      try {
        const isReady = await checkServiceReady();
        if (!cancelled && isReady) {
          setServiceReady(true);
        }
      } catch {
        // 网络错误忽略，下次轮询继续
      }
    };

    // 每 2 秒轮询一次
    const interval = setInterval(checkReady, 2000);
    checkReady(); // 立即执行一次

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [serviceReady]);

  // 当服务就绪且最小展示时间已到达时，标记加载动画完成
  useEffect(() => {
    if (serviceReady && timeElapsed) {
      setReady(true);
    }
  }, [serviceReady, timeElapsed]);

  return ready;
};
