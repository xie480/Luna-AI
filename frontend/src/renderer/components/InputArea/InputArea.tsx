import React, { useState, useRef, useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { wsManager } from '../../services/wsManager';
import './InputArea.css';

export const InputArea: React.FC = () => {
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const addSystemLog = useSystemStore.getState().addSystemLog;

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
      <div className="input-area">
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
      </div>
    </div>
  );
};
