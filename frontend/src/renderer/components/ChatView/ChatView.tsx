/**
 * Luna AI 聊天视图组件
 * 主界面核心组件，负责展示用户与 AI 的交互消息
 * 严格遵循 Go Runtime 为唯一状态权威的原则，所有状态来自 Zustand Store
 */
import React from 'react';
import { Live2DView } from '../Live2DView/Live2DView';
import { BackgroundLayer } from '../BackgroundLayer/BackgroundLayer';
import { TopStatusPanel } from '../TopStatusPanel/TopStatusPanel';
import { BubbleStack } from '../BubbleStack/BubbleStack';
import { InputArea } from '../InputArea/InputArea';
import ErrorBoundary from '../ErrorBoundary/ErrorBoundary';
import './ChatView.css';

/**
 * 聊天视图组件
 * 占据主界面全部空间，提供沉浸式聊天体验
 * 使用 ErrorBoundary 包裹关键子组件，防止局部异常导致整个页面白屏
 */
export const ChatView: React.FC = () => {
  return (
    <div className="chat-view">
      {/* 背景层 z-index: 0 */}
      <BackgroundLayer />

      {/* Live2D 角色层 z-index: 10 */}
      <div className="live2d-layer">
        <ErrorBoundary source="live2d_view">
          <Live2DView />
        </ErrorBoundary>
      </div>

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
