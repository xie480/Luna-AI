import { useState, useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';

/**
 * 监听后端服务 (Go Runtime + Python AI Service) 是否已经就绪。
 * 只有在 `connectionStatus` 与 `aiConnectionStatus` 同时为 'connected' 且
 * 最小加载时间已到达时返回 true，确保加载动画拥有足够的观赏时间。
 */
export const useBackendReady = (minLoadingTimeMs = 2000) => {
  const [ready, setReady] = useState(false);
  const [timeElapsed, setTimeElapsed] = useState(false);

  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const aiConnectionStatus = useSystemStore((state) => state.aiConnectionStatus);

  // 确保加载动画至少展示指定时长
  useEffect(() => {
    const timer = setTimeout(() => setTimeElapsed(true), minLoadingTimeMs);
    return () => clearTimeout(timer);
  }, [minLoadingTimeMs]);

  // 当后端状态满足且时间已到达时标记就绪
  useEffect(() => {
    // 只要 connectionStatus 是 connected，就认为后端就绪。
    // 因为 aiConnectionStatus 的更新依赖于 PONG 消息，而 PONG 消息可能不会在启动时立即发送。
    // 只要 SSE 连接成功，就说明 Go Runtime 已经启动，可以进入主界面。
    const backendConnected = connectionStatus === 'connected';
    
    if (backendConnected && timeElapsed) {
      setReady(true);
    }
  }, [connectionStatus, aiConnectionStatus, timeElapsed]);

  return ready;
};
