import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSystemStore } from '../../stores/systemStore';
import { useVisualStatusQueue, VisualStateItem } from '../../stores/visualStatusQueueStore';
import { OrbitalArcContainer } from './OrbitalArcContainer';
import './TopStatusPanel.css';

/**
 * TopStatusPanel — 顶部状态信息面板。
 *
 * 做什么：渲染聊天工作流的状态通知（由后端 ChatStatusPublisher 通过 EVT_CHAT_STATUS 推送）。
 *         状态文案集中由后端 _CHAT_STATUS_TEXTS 管理，前端仅根据 stage/state 渲染对应 display_text。
 *         同时根据后端连接状态（connectionStatus）驱动状态栏的视觉主题切换：
 *
 *         状态机流转逻辑（对应 sse_chat_status_holographic_arc_impl.md §1.1）：
 *
 *         1. 连接状态不健康（connecting / disconnected / reconnecting）
 *            → 强制进入"离线/异常态"，呈现"引力塌缩与空间撕裂"视觉主题（§1.1 第五段）：
 *            - 主星变为尖锐荧光红 #FF3333，高频不规则跳跃
 *            - 轨道变为锯齿毛刺虚线
 *            - 文本显示"空间站链接中断"或"正在连接空间站..."
 *            - 屏蔽一切来自后端的 chat_status 队列，防止后端已断开时的残留状态覆盖错误提示
 *
 *         2. 连接状态健康（connected）+ 无活跃队列（currentVisualState === null）
 *            → 进入"空闲态"，呈现"深空潜伏"视觉主题（§1.1 第一段）：
 *            - TrackBackground 轨道 opacity 降至 0.05
 *            - StarEntity 主星收缩为 scale: 0.2 的白矮星，以 4s 周期深长呼吸
 *            - 文本容器完全折叠（无文字显示）
 *
 *         3. 连接状态健康（connected）+ 有活跃队列（currentVisualState !== null）
 *            → 正常渲染后端推送的状态，展示"星轨跃迁"或"神经连结供能"等主题
 *
 * 为什么这样做：之前的设计在 connectionStatus 跃迁时（disconnected→connected）才触发清除，
 *             但没有持续覆盖逻辑。如果连接中途断开且没有跃迁（如初始化时就是 disconnected），
 *             状态栏可能显示后端残留的状态而不是立即进入离线/异常态。
 *             现在的方案改为：在渲染层直接根据 connectionStatus 计算 displayVisualState，
 *             当连接不健康时无条件覆盖所有状态，保证离线态不被任何聊天状态覆盖。
 *
 * 边界条件：
 *   - 初始挂载时 connectionStatus === 'disconnected'，立即显示离线异常态
 *   - connected → disconnected 时覆盖所有队列状态，显示断连错误提示
 *   - connecting 状态时显示"正在连接空间站..."
 *   - connected + 无活跃状态 → 空闲态"深空潜伏"
 *   - connected + 有活跃状态 → 正常渲染
 */
export const TopStatusPanel: React.FC = () => {
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const { currentVisualState, queue } = useVisualStatusQueue();

  /**
   * 根据 connectionStatus 计算当前应展示的 VisualStateItem。
   * 当连接不健康时，强制覆盖 currentVisualState 为离线/异常态，
   * 确保状态栏准确进入"引力塌缩与空间撕裂"视觉主题。
   */
  const displayVisualState: VisualStateItem | null = (() => {
    if (connectionStatus === 'connected') {
      // 已连接：透传后端状态（或 null 触发空闲态"深空潜伏"）
      return currentVisualState;
    }
    // 未连接：强制进入离线/异常态
    const text = connectionStatus === 'connecting' || connectionStatus === 'reconnecting'
      ? '正在连接空间站...'
      : '空间站链接中断，尝试重连...';
    return {
      id: 'sys-offline',
      stage: 'SYSTEM',
      state: 'ERROR',
      text,
      colorTheme: 'red',
      isTerminal: false,
    };
  })();

  /**
   * 从未连接 → 连接成功的跃迁处理。
   * 清空队列和当前状态，确保状态栏从离线/异常态平滑过渡到空闲态"深空潜伏"
   * 或者如果后端正在推送工作流状态，则立即跟进处理中的状态。
   */
  useEffect(() => {
    if (connectionStatus === 'connected') {
      const store = useVisualStatusQueue.getState();
      store.clearToIdle();
    }
  }, [connectionStatus]);

  // 如果没有活跃状态（空闲态），使用蓝色主题；否则使用当前状态主题色
  const themeClass = displayVisualState?.colorTheme || 'blue';
  // 空闲态标识：已连接 + 无活跃状态 → "深空潜伏"
  const idleClass = (connectionStatus === 'connected' && !displayVisualState) ? 'idle-connected' : '';

  return (
    <div className={`top-status-panel theme-${themeClass} ${idleClass}`}>
      {/*
        主题环境光晕 — 在文字下方柔和的呼吸发光光晕
        与轨道特效完美嵌套，使用独立形变周期
      */}
      <AnimatePresence mode="wait">
        {displayVisualState?.text && (
          <motion.div
            key={`aura-${displayVisualState.colorTheme}`}
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
        currentVisualState={displayVisualState}
        queueLength={queue.length}
        idleTheme="blue"
      />
    </div>
  );
};
