import React, { useEffect, useRef, useState } from 'react';
import { useHistoryStore, HistoryChatMessage } from '../../stores/historyStore';
import { useLongAnswerStore } from '../../stores/longAnswerStore';
import { longAnswerService } from '../../services/longAnswerService';
import './ChatHistoryView.css';

/**
 * 单条聊天消息组件
 * 负责渲染用户消息、Luna 回复以及错误消息。
 * Luna 回复支持点击爱心图标翻转查看内心独白。
 */
const ChatMessageItem: React.FC<{
  msg: HistoryChatMessage;
  formatTime: (date: string) => string;
}> = ({ msg, formatTime }) => {
  const isUser = msg.role === 'user';
  const [isFlipped, setIsFlipped] = useState(false);

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
      <div className="message-wrapper error-block">
        <div className="message-bubble">
          <div className="error-header">响应异常</div>
          <div className="message-content">{errorContent}</div>
        </div>
        <div className="message-time-row">
          <div className="message-time">{formatTime(msg.created_at)}</div>
        </div>
      </div>
    );
  }

  if (isUser) {
    return (
      <div className="message-wrapper user">
        <div className="message-bubble">
          <div className="message-content">{msg.content}</div>
        </div>
        <div className="message-time-row">
          <div className="message-time">{formatTime(msg.created_at)}</div>
        </div>
      </div>
    );
  }

  /**
   * Luna 助手消息：支持内心独白翻转动画
   * 使用 CSS Grid 的 grid-template-rows: 0fr → 1fr 实现高度自适应撑开动画
   */
  return (
    <div className="message-wrapper assistant">
      <div className="message-bubble-container">
        {/* 正面：常规回复 */}
        <div className={`bubble-face front ${!isFlipped ? 'active' : ''}`}>
          <div className="bubble-content-wrapper">
            <div className="message-bubble">
              <div className="message-content">{msg.content}</div>
            </div>
          </div>
        </div>
        {/* 背面：内心独白 */}
        <div className={`bubble-face back ${isFlipped ? 'active' : ''}`}>
          <div className="bubble-content-wrapper">
            <div className="message-bubble">
              <div className="message-content">{msg.thought || '（没有记录内心活动）'}</div>
            </div>
          </div>
        </div>
      </div>
      <div className="message-time-row">
        <div className="message-time">{formatTime(msg.created_at)}</div>
        {/* 文档图标按钮（如存在长回答） */}
        {msg.metadata?.hasLongAnswer && msg.metadata?.longAnswerId && (
          <button
            className="action-icon-btn document-icon-btn"
            style={{ zIndex: 100, position: 'relative' }}
            onClick={async (e) => {
              e.stopPropagation();
              e.preventDefault();
              const id = msg.metadata!.longAnswerId as string;
              const { openPanel, updateStatus, byId } = useLongAnswerStore.getState();
              
              if (!byId[id]) {
                updateStatus(id, { status: 'PENDING', title: '加载中...' });
              }
              openPanel(id);
              
              try {
                const data = await longAnswerService.fetchLongAnswerById(id);
                if (data) {
                  useLongAnswerStore.getState().updateStatus(id, {
                    status: data.status || 'COMPLETED',
                    markdown: data.content_markdown || '',
                    title: data.title || '整理完成',
                    shortSummary: data.short_summary || '',
                    citations: data.citations || [],
                  });
                } else {
                   useLongAnswerStore.getState().updateStatus(id, {
                    status: 'FAILED',
                    errorMessage: '未能获取到长回答内容',
                  });
                }
              } catch (err) {
                console.error("Failed to load long answer content:", err);
                useLongAnswerStore.getState().updateStatus(id, {
                  status: 'FAILED',
                  errorMessage: String(err),
                });
              }
            }}
            title="查看文档内容"
            aria-label="查看文档内容"
          >
            <svg
              viewBox="0 0 24 24"
              width="12"
              height="12"
              stroke="currentColor"
              strokeWidth="2"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
          </button>
        )}
        {/* 操作图标按钮：爱心图标 / 返回图标 */}
        <button
          className={`action-icon-btn ${isFlipped ? 'flipped' : ''}`}
          onClick={() => setIsFlipped(!isFlipped)}
          title={isFlipped ? '返回常规回复' : '查看内心独白'}
          aria-label={isFlipped ? '返回常规回复' : '查看内心独白'}
        >
          {isFlipped ? (
            /* 返回箭头 SVG 图标 */
            <svg
              viewBox="0 0 24 24"
              width="12"
              height="12"
              stroke="currentColor"
              strokeWidth="2"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="9 14 4 9 9 4" />
              <path d="M20 20v-7a4 4 0 0 0-4-4H4" />
            </svg>
          ) : (
            /* 爱心 SVG 图标 */
            <svg
              viewBox="0 0 24 24"
              width="12"
              height="12"
              stroke="currentColor"
              strokeWidth="2"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
};

/**
 * 聊天历史视图组件
 * 展示选定日期的聊天记录列表，支持加载状态和空状态。
 */
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
        <div className="loading-spinner" />
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
        {chatHistory.map((msg) => (
          <ChatMessageItem key={msg.id} msg={msg} formatTime={formatTime} />
        ))}
      </div>
    </div>
  );
};
