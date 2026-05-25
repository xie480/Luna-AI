/**
 * Luna AI 聊天视图组件
 * 主界面核心组件，负责展示用户与 AI 的交互消息
 * 严格遵循 Go Runtime 为唯一状态权威的原则，所有状态来自 Zustand Store
 */
import React, { useEffect, useRef, useState } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useSystemStore } from '../../stores/systemStore';
import { wsManager } from '../../services/wsManager';
import './ChatView.css';

/**
 * 聊天视图组件
 * 占据主界面全部空间，提供沉浸式聊天体验
 */
export const ChatView: React.FC = () => {
  // 从 Store 获取状态
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const messages = useSessionStore((state) =>
    currentSessionId ? state.messages[currentSessionId] || [] : []
  );
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const addSystemLog = useSystemStore.getState().addSystemLog;

  // 本地状态：输入框内容
  const [inputValue, setInputValue] = useState('');
  // 本地状态：是否正在生成回复
  const [isGenerating, setIsGenerating] = useState(false);

  // 消息列表底部引用，用于自动滚动
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 输入框引用
  const inputRef = useRef<HTMLInputElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 监听消息状态，更新生成状态
  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    if (lastMessage && lastMessage.role === 'assistant') {
      setIsGenerating(lastMessage.status === 'streaming');
    }
  }, [messages]);

  /**
   * 发送消息
   * 将用户输入发送到 Go Runtime，由 Go 控制后续流程
   */
  const handleSendMessage = (): void => {
    if (!inputValue.trim() || isGenerating) return;

    if (connectionStatus !== 'connected') {
      addSystemLog('WebSocket 未连接，无法发送消息');
      return;
    }

    wsManager.sendChatMessage(inputValue.trim());
    setInputValue('');
    inputRef.current?.focus();
  };

  /**
   * 处理键盘事件
   * Enter 键发送消息
   */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  /**
   * 渲染单条消息
   */
  const renderMessage = (msg: {
    messageId: string;
    role: string;
    content: string;
    status: string;
    error?: string;
  }): React.ReactNode => {
    const isUser = msg.role === 'user';
    const isStreaming = msg.status === 'streaming';
    const hasError = msg.status === 'error';

    return (
      <div
        key={msg.messageId}
        className={`chat-message ${isUser ? 'user-message' : 'assistant-message'}`}
      >
        <div className={`message-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`}>
          <div className="message-content">
            {msg.content}
            {/* 流式输出时的光标动画 */}
            {isStreaming && !isUser && (
              <span className="streaming-cursor"></span>
            )}
          </div>
          {/* 错误提示 */}
          {hasError && msg.error && (
            <div className="message-error">错误: {msg.error}</div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="chat-view">
      {/* 消息列表区域 */}
      <div className="messages-container">
        {messages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">🌙</div>
            <div className="empty-text">开始与 Luna 对话吧...</div>
          </div>
        ) : (
          messages.map(renderMessage)
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="input-container">
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={connectionStatus === 'connected' ? '输入消息...' : '等待连接...'}
          disabled={connectionStatus !== 'connected' || isGenerating}
          className="chat-input"
        />
        <button
          onClick={handleSendMessage}
          disabled={connectionStatus !== 'connected' || isGenerating || !inputValue.trim()}
          className="send-button"
        >
          发送
        </button>
      </div>

      {/* 连接状态指示器 */}
      <div className={`connection-indicator ${connectionStatus}`}>
        {connectionStatus === 'connected' && '● 已连接'}
        {connectionStatus === 'connecting' && '○ 连接中...'}
        {connectionStatus === 'reconnecting' && '○ 重连中...'}
        {connectionStatus === 'disconnected' && '○ 未连接'}
      </div>
    </div>
  );
};