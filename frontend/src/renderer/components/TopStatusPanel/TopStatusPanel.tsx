import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSystemStore } from '../../stores/systemStore';
import { useVisualStatusQueue } from '../../stores/visualStatusQueueStore';
import { OrbitalArcContainer } from './OrbitalArcContainer';
import './TopStatusPanel.css';

/**
 * TopStatusPanel — 顶部状态信息面板。
 *
 * 做什么：渲染聊天工作流的状态通知（由后端 ChatStatusPublisher 通过 EVT_CHAT_STATUS 推送）。
 *         状态文案集中由后端 _CHAT_STATUS_TEXTS 管理，前端仅根据 stage/state 渲染对应 display_text。
 *         同时监听连接状态变化：
 *           - connected → disconnected：显示断连错误提示（红）
 *           - disconnected → connected：回到空闲态"深空潜伏"
 *
 * 空闲态"深空潜伏"视觉表现（详见 sse_chat_status_holographic_arc_impl.md §1.1）：
 *   - 根据当前是否已连接，使用不同的透明度和呼吸频率。已连接时为极微弱蓝色呼吸，未连接且无错误时为静默。
 *   - TrackBackground 轨道 opacity 降至 0.05，如同隐匿在暗物质中的星轨
 *   - StarEntity 主星收缩为 scale: 0.2 的白矮星，以 4s 周期深长呼吸
 *   - 文本容器完全折叠（无文字显示）
 *
 * 为什么这样做：状态文案必须由后端按 node 粒度精准推送，前端不应在前端硬编码或自行拼装状态文案。
 * 边界条件：无活跃计划且连接正常时状态栏保持在"深空潜伏"空闲态。
 */
export const TopStatusPanel: React.FC = () => {
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const { currentVisualState, queue } = useVisualStatusQueue();
  
  // 使用本地状态跟踪是否应显示未连接的空闲态，避免与断连报错冲突
  const [idleTheme, setIdleTheme] = useState<'blue' | 'gray'>('gray');

  // 记录上一次连接状态，用于判断是否发生了 "connected ↔ disconnected" 的跃迁
  const prevConnectionRef = useRef<string>(connectionStatus);

  // 监听连接状态跃迁
  useEffect(() => {
    const prev = prevConnectionRef.current;
    prevConnectionRef.current = connectionStatus;

    if (connectionStatus === 'connected') {
      setIdleTheme('blue'); // 已连接的空闲态为幽蓝
    } else {
      setIdleTheme('gray'); // 未连接的空闲态为灰暗
    }

    if (connectionStatus === 'disconnected' && prev === 'connected') {
      // connected → disconnected 跃迁：显示断连错误提示
      const { enqueue, clearToIdle } = useVisualStatusQueue.getState();
      clearToIdle();
      enqueue({
        id: `sys-disconnected-${Date.now()}`,
        stage: 'SYSTEM',
        state: 'ERROR',
        text: '空间站链接中断，尝试重连...',
        colorTheme: 'red',
      });
    } else if (connectionStatus === 'connected' && prev !== 'connected') {
      // disconnected → connected 跃迁：进入"深空潜伏"空闲态
      // currentVisualState = null 触发 StarEntity 的 IDLE variant 和 TrackBackground 的 0.05 opacity
      useVisualStatusQueue.getState().clearToIdle();
    }
    // 初始挂载时 prev === 'disconnected' && connectionStatus === 'disconnected'，不触发任何操作
  }, [connectionStatus]);

  // 如果没有活跃状态，则使用空闲态的配置
  const themeClass = currentVisualState?.colorTheme || idleTheme;
  // 注入一个额外的 css 类来标识是否处于未连接的空闲态
  const idleClass = (!currentVisualState && connectionStatus !== 'connected') ? 'idle-disconnected' : '';

  return (
    <div className={`top-status-panel theme-${themeClass} ${idleClass}`}>
      {/*
        主题环境光晕 — 在文字下方柔和的呼吸发光光晕
        与轨道特效完美嵌套，使用独立形变周期
      */}
      <AnimatePresence mode="wait">
        {currentVisualState?.text && (
          <motion.div
            key={`aura-${currentVisualState.colorTheme}`}
            className="status-aura-glow"
            initial={{ opacity: 0, scaleX: 0.8, scaleY: 0.5 }}
            animate={{ 
              opacity: [0.3, 0.8, 0.2, 0.9, 0.4], 
              scaleX: [0.85, 1.05, 0.9, 1.1, 0.85], 
              scaleY: [0.6, 1.0, 0.7, 0.9, 0.6] 
            }}
            exit={{ opacity: 0, scaleX: 0.8, scaleY: 0.5, transition: { duration: 0.3 } }}
            transition={{
              duration: 3.5,
              times: [0, 0.15, 0.4, 0.75, 1],
              ease: "circInOut",
              repeat: Infinity,
            }}
          />
        )}
      </AnimatePresence>

      <OrbitalArcContainer
        currentVisualState={currentVisualState}
        queueLength={queue.length}
      />
    </div>
  );
};
