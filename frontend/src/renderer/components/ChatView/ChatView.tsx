/**
 * Luna AI 聊天视图组件
 * 主界面核心组件，负责展示用户与 AI 的交互消息
 * 严格遵循 Go Runtime 为唯一状态权威的原则，所有状态来自 Zustand Store
 *
 * Phase 5 新增：引入 RecentMemoryPanel 右上角近期记忆面板
 *
 * 关键优化：Live2DView 延迟挂载
 * 卡顿根因：加载动画（EventHorizonLoader）的 WebGL Canvas 销毁与
 * Live2DView 的 PIXI 初始化在同一帧发生，GPU 上下文切换导致帧率骤降。
 * 解决方案：等待 luna:loading-complete 事件触发后再挂载 Live2DView，
 * 确保两个 WebGL 上下文的创建与销毁完全错开。
 */
import React, { useEffect, useState } from 'react';
import { Live2DView } from '../Live2DView/Live2DView';
import { BackgroundLayer } from '../BackgroundLayer/BackgroundLayer';
import { TopStatusPanel } from '../TopStatusPanel/TopStatusPanel';
import { BubbleStack } from '../BubbleStack/BubbleStack';
import { InputArea } from '../InputArea/InputArea';
import { RecentMemoryPanel } from '../RecentMemoryPanel/RecentMemoryPanel';
import { HolographicWorkflowSidebar } from '../HolographicWorkflow/HolographicWorkflowSidebar';
import { DagWorkflowPanel } from '../DagWorkflow/DagWorkflowPanel';
import ErrorBoundary from '../ErrorBoundary/ErrorBoundary';
import { createErrorToast } from '../../stores/errorToastStore';
import { reportError } from '../../services/errorLogService';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE } from '../../../shared/enum';
import './ChatView.css';

/**
 * 聊天视图组件
 * 占据主界面全部空间，提供沉浸式聊天体验
 * 使用 ErrorBoundary 包裹关键子组件，防止局部异常导致整个页面白屏
 *
 * 延迟挂载策略：
 * Live2DView（PIXI + WebGL）初始化的开销较大，包含：
 *   - 创建新的 PIXI.Application（WebGL 上下文）
 *   - 通过 HTTP 加载 Live2D 模型文件（.model3.json + 贴图 + 动作）
 *   - 初始化模型核心与表情缓存
 * 如果这些操作与加载动画的 Canvas 销毁发生在同一帧，会造成明显的卡顿抖动。
 * 因此，Live2DView 仅在接收到 luna:loading-complete 事件后才挂载，
 * 确保加载动画的 WebGL 资源已完全释放。
 */
export const ChatView: React.FC = () => {
  // Live2DView 延迟挂载状态：强制设为 true 以进行诊断
  const [live2dReady] = useState(true);
  const isLive2dEnabled = useSystemStore((state) => state.isLive2dEnabled);
  const chatMode = useSystemStore((state) => state.chatMode);

  // 暂时注释掉延迟挂载逻辑，强制渲染 Live2DView
  // useEffect(() => {
  //   if ((window as any).__LUNA_LOADING_COMPLETE__) {
  //     setLive2dReady(true);
  //     return;
  //   }
  //   const handleLoadingComplete = () => {
  //     requestAnimationFrame(() => {
  //       setLive2dReady(true);
  //     });
  //   };
  //   window.addEventListener('luna:loading-complete', handleLoadingComplete);
  //   if ((window as any).__LUNA_LOADING_COMPLETE__) {
  //     setLive2dReady(true);
  //   }
  //   return () => {
  //     window.removeEventListener('luna:loading-complete', handleLoadingComplete);
  //   };
  // }, []);

  useEffect(() => {
    /**
     * 监听 luna:notification 自定义事件
     * 替代旧的 alert() 弹窗，改为使用 ErrorToast 组件展示
     * 同时将错误信息持久化到数据库
     */
    const handleNotification = (e: Event) => {
      const customEvent = e as CustomEvent;
      const { message, type, source, detail } = customEvent.detail;

      // 确定错误级别
      const level = type === 'error' ? 'ERROR' : type === 'warning' ? 'WARN' : 'ERROR';
      const errorSource = source || 'notification';

      // 1. 显示 UI 错误提示
      createErrorToast(level, errorSource, message, detail);

      // 2. 异步持久化到数据库（不阻塞 UI）
      reportError(errorSource, message, detail || '').catch(() => { /* 静默降级 */ });
    };

    window.addEventListener('luna:notification', handleNotification);
    return () => {
      window.removeEventListener('luna:notification', handleNotification);
    };
  }, []);

  return (
    <div className="chat-view">
      {/* 背景层 z-index: 0 */}
      <BackgroundLayer />

      {/* Live2D 角色层 z-index: 10 — 延迟挂载，避免与加载动画 GPU 上下文冲突 */}
      {live2dReady && isLive2dEnabled && (
        <div className="live2d-layer">
          <ErrorBoundary source="live2d_view">
            <Live2DView />
          </ErrorBoundary>
        </div>
      )}

      {/* 近期记忆面板层 z-index: 25 — 位于交互层之上，右上角 */}
      <RecentMemoryPanel />

      {/* 工作流侧边栏 (Holographic UI) — 日常聊天/极速闲聊模式 */}
      <ErrorBoundary source="workflow_sidebar">
         <HolographicWorkflowSidebar />
      </ErrorBoundary>

      {/* Phase 9：DAG 深度工作流面板 — 智能规划模式 */}
      {chatMode === CHAT_MODE.PLAN_STATE_NODE && (
        <ErrorBoundary source="dag_workflow_panel">
          <DagWorkflowPanel />
        </ErrorBoundary>
      )}

      {/* 交互层 z-index: 20 */}
      <div className="interaction-layer">
        <ErrorBoundary source="chat_view">
          <TopStatusPanel />
          <BubbleStack />
          <InputArea />
        </ErrorBoundary>
      </div>
    </div>
  );
};
