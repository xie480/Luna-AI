import React, { useState, useRef, useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { useSessionStore } from '../../stores/sessionStore';
import { wsManager } from '../../services/wsManager';
import './InputArea.css';

export const InputArea: React.FC = () => {
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const addSystemLog = useSystemStore.getState().addSystemLog;

  // 检查是否正在等待响应（有 sending 或 streaming 状态的消息）
  const isWaiting = useSessionStore((state) => {
    const sessionId = state.currentSessionId;
    if (!sessionId) return false;
    const msgs = state.messages[sessionId] || [];
    return msgs.some((m) => m.status === 'sending' || m.status === 'streaming');
  });

  // 自动聚焦：连接成功且不在等待状态时聚焦
  useEffect(() => {
    if (connectionStatus === 'connected' && !isWaiting) {
      inputRef.current?.focus();
    }
  }, [connectionStatus, isWaiting]);

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;

    if (connectionStatus !== 'connected') {
      addSystemLog('WebSocket 未连接，无法发送消息');
      return;
    }

    wsManager.sendChatMessage(inputValue.trim());
    setInputValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="input-area-wrapper">
      <div className={`input-area ${isWaiting ? 'waiting' : ''}`}>
        
        {/* 炫酷的 Cyber-Neural 加载动画 */}
        <div className={`cyber-loader ${isWaiting ? 'active' : ''}`}>
          <div className="cyber-text">
            <span className="cyber-dot"></span>
            PROCESSING
            <span className="cyber-dot"></span>
          </div>
        </div>

        {/* 输入框始终存在于 DOM 中，通过 CSS 控制显隐，彻底解决布局偏移 */}
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={connectionStatus === 'connected' ? '和她说点什么...' : '等待连接...'}
          disabled={connectionStatus !== 'connected' || isWaiting}
          className={`quiet-input ${isWaiting ? 'hidden' : ''}`}
        />
        
      </div>
    </div>
  );
};
