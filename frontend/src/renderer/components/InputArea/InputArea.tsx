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

  // 自动聚焦
  useEffect(() => {
    if (connectionStatus === 'connected') {
      inputRef.current?.focus();
    }
  }, [connectionStatus]);

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;

    if (connectionStatus !== 'connected') {
      addSystemLog('WebSocket 未连接，无法发送消息');
      return;
    }

    wsManager.sendChatMessage(inputValue.trim());
    setInputValue('');
    inputRef.current?.focus();
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
        {isWaiting ? (
          <div className="loading-indicator">
            <span className="loading-dot dot-1">.</span>
            <span className="loading-dot dot-2">.</span>
            <span className="loading-dot dot-3">.</span>
          </div>
        ) : (
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={connectionStatus === 'connected' ? '和她说点什么...' : '等待连接...'}
            disabled={connectionStatus !== 'connected'}
            className="quiet-input"
          />
        )}
      </div>
    </div>
  );
};
