import React, { useEffect, useRef } from 'react';
import { useHistoryStore } from '../../stores/historyStore';
import './ChatHistoryView.css';

export const ChatHistoryView: React.FC = () => {
  const { chatHistory, isLoadingHistory, selectedDate } = useHistoryStore();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatHistory]);

  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  if (isLoadingHistory) {
    return (
      <div className="chat-history-view loading">
        <div className="loading-spinner"></div>
        <span className="loading-text">正在读取记忆...</span>
      </div>
    );
  }

  if (!chatHistory || chatHistory.length === 0) {
    return (
      <div className="chat-history-view empty">
        <span className="empty-text">这一天没有留下记忆</span>
      </div>
    );
  }

  return (
    <div className="chat-history-view">
      <div className="chat-header">
        <span className="chat-date">{selectedDate}</span>
      </div>
      <div className="chat-messages" ref={scrollRef}>
        {chatHistory.map((msg) => {
          const isUser = msg.role === 'user';
          
          // 异常响应容错渲染
          let isError = false;
          let errorContent = msg.content;
          if (!isUser && msg.content.includes('"error":')) {
            try {
              const parsed = JSON.parse(msg.content);
              if (parsed.error) {
                isError = true;
                errorContent = JSON.stringify(parsed, null, 2);
              }
            } catch (e) {
              // 解析失败，按普通文本处理
            }
          }

          if (isError) {
            return (
              <div key={msg.id} className="message-wrapper error-block">
                <div className="message-bubble">
                  <div className="error-header">响应异常</div>
                  <div className="message-content">{errorContent}</div>
                </div>
                <div className="message-time">{formatTime(msg.created_at)}</div>
              </div>
            );
          }

          return (
            <div key={msg.id} className={`message-wrapper ${isUser ? 'user' : 'assistant'}`}>
              <div className="message-bubble">
                <div className="message-content">{msg.content}</div>
              </div>
              <div className="message-time">{formatTime(msg.created_at)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
