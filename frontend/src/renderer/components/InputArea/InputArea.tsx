import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { useSessionStore } from '../../stores/sessionStore';
import { wsManager } from '../../services/wsManager';
import './InputArea.css';

/**
 * 高级文本输入框组件
 * 
 * 功能特性：
 * 1. 动态自适应高度：文本超过当前宽度时自动换行并平滑扩展高度
 * 2. 高度限制：达到三行文本高度后停止扩展，转为内部滚动
 * 3. 全屏编辑模式：达到高度限制时显示全屏按钮，点击进入沉浸式大屏编辑
 * 
 * @author Luna AI Team
 */
export const InputArea: React.FC = () => {
  // 输入框内容
  const [inputValue, setInputValue] = useState('');
  // 是否显示全屏按钮（当文本超过三行时显示）
  const [showFullscreenButton, setShowFullscreenButton] = useState(false);
  // 是否处于全屏编辑模式
  const [isFullscreenMode, setIsFullscreenMode] = useState(false);
  // 全屏模式下的文本内容
  const [fullscreenText, setFullscreenText] = useState('');
  
  // textarea 引用
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // 全屏模式 textarea 引用
  const fullscreenTextareaRef = useRef<HTMLTextAreaElement>(null);
  // 隐藏的测量层引用，用于计算文本高度
  const measureRef = useRef<HTMLDivElement>(null);
  
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const addSystemLog = useSystemStore.getState().addSystemLog;

  // 单行文本高度（像素）
  const LINE_HEIGHT = 24;
  // 最大行数限制
  const MAX_LINES = 3;
  // 最大高度（三行 + padding）
  const MAX_HEIGHT = LINE_HEIGHT * MAX_LINES + 24;

  // 检查是否正在等待响应（有 sending 或 streaming 状态的消息）
  const isWaiting = useSessionStore((state) => {
    const sessionId = state.currentSessionId;
    if (!sessionId) return false;
    const msgs = state.messages[sessionId] || [];
    return msgs.some((m) => m.status === 'sending' || m.status === 'streaming');
  });

  /**
   * 自适应高度调整
   * 当文本超过一行时自动扩展，达到三行后停止扩展并显示滚动条
   */
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    // 重置高度以获取正确的 scrollHeight
    textarea.style.height = 'auto';
    
    const scrollHeight = textarea.scrollHeight;
    const newHeight = Math.min(scrollHeight, MAX_HEIGHT);
    
    // 设置新高度
    textarea.style.height = `${newHeight}px`;
    
    // 判断是否需要显示全屏按钮
    // 当内容高度接近或超过最大高度时显示
    const shouldShowButton = scrollHeight > MAX_HEIGHT - LINE_HEIGHT / 2;
    setShowFullscreenButton(shouldShowButton);
    
    // 如果内容超过最大高度，启用滚动
    if (scrollHeight > MAX_HEIGHT) {
      textarea.style.overflowY = 'auto';
    } else {
      textarea.style.overflowY = 'hidden';
    }
  }, [MAX_HEIGHT]);

  // 监听输入内容变化，调整高度
  useEffect(() => {
    adjustHeight();
  }, [inputValue, adjustHeight]);

  // 自动聚焦：连接成功且不在等待状态时聚焦
  useEffect(() => {
    if (connectionStatus === 'connected' && !isWaiting && !isFullscreenMode) {
      textareaRef.current?.focus();
    }
  }, [connectionStatus, isWaiting, isFullscreenMode]);

  // 全屏模式打开时自动聚焦
  useEffect(() => {
    if (isFullscreenMode) {
      // 延迟聚焦以确保动画完成
      setTimeout(() => {
        fullscreenTextareaRef.current?.focus();
      }, 100);
    }
  }, [isFullscreenMode]);

  /**
   * 发送消息处理
   */
  const handleSendMessage = () => {
    const textToSend = isFullscreenMode ? fullscreenText : inputValue;
    if (!textToSend.trim()) return;

    if (connectionStatus !== 'connected') {
      addSystemLog('WebSocket 未连接，无法发送消息');
      return;
    }

    wsManager.sendChatMessage(textToSend.trim());
    
    // 清空对应输入框
    if (isFullscreenMode) {
      setFullscreenText('');
      setIsFullscreenMode(false);
    } else {
      setInputValue('');
    }
  };

  /**
   * 键盘事件处理
   * Enter 发送，Shift+Enter 换行
   */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  /**
   * 打开全屏编辑模式
   */
  const openFullscreenMode = () => {
    setFullscreenText(inputValue);
    setIsFullscreenMode(true);
  };

  /**
   * 关闭全屏编辑模式
   * 将全屏模式的内容同步回主输入框
   */
  const closeFullscreenMode = () => {
    setInputValue(fullscreenText);
    setIsFullscreenMode(false);
    setShowFullscreenButton(false);
  };

  /**
   * 全屏模式下的键盘事件
   * 支持 Escape 关闭
   */
  const handleFullscreenKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeFullscreenMode();
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <>
      {/* 隐藏的测量层，用于计算文本高度 */}
      <div
        ref={measureRef}
        className="input-measure-layer"
        aria-hidden="true"
      />

      {/* 主输入区域 */}
      <div className="input-area-wrapper">
        <div className={`input-area ${isWaiting ? 'waiting' : ''} ${showFullscreenButton ? 'has-fullscreen-btn' : ''}`}>
          
          {/* 炫酷的 Cyber-Neural 加载动画 */}
          <div className={`cyber-loader ${isWaiting ? 'active' : ''}`}>
            <div className="cyber-text">
              <span className="cyber-dot"></span>
              PROCESSING
              <span className="cyber-dot"></span>
            </div>
          </div>

          {/* 多行文本输入框 */}
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={connectionStatus === 'connected' ? '' : '等待连接...'}
            disabled={connectionStatus !== 'connected' || isWaiting}
            className={`quiet-textarea ${isWaiting ? 'hidden' : ''}`}
            rows={1}
          />

          {/* 全屏编辑按钮 */}
          {showFullscreenButton && !isWaiting && (
            <button
              className="fullscreen-btn"
              onClick={openFullscreenMode}
              title="全屏编辑"
              aria-label="展开全屏编辑模式"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
              </svg>
            </button>
          )}
          
        </div>
      </div>

      {/* 全屏编辑模态框 */}
      {isFullscreenMode && (
        <div className="fullscreen-modal-overlay" onClick={closeFullscreenMode}>
          <div 
            className="fullscreen-modal" 
            onClick={(e) => e.stopPropagation()}
          >
            {/* 模态框头部 */}
            <div className="fullscreen-modal-header">
              <h3 className="fullscreen-modal-title">沉浸式编辑</h3>
              <div className="fullscreen-modal-actions">
                <button
                  className="fullscreen-action-btn send-btn"
                  onClick={handleSendMessage}
                  disabled={!fullscreenText.trim() || connectionStatus !== 'connected'}
                  title="发送消息"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
                  </svg>
                  <span>发送</span>
                </button>
                <button
                  className="fullscreen-action-btn close-btn"
                  onClick={closeFullscreenMode}
                  title="关闭 (Esc)"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
            
            {/* 全屏文本编辑区 */}
            <div className="fullscreen-editor-container">
              <textarea
                ref={fullscreenTextareaRef}
                value={fullscreenText}
                onChange={(e) => setFullscreenText(e.target.value)}
                onKeyDown={handleFullscreenKeyDown}
                placeholder="在这里输入你想说的话..."
                className="fullscreen-textarea"
                autoFocus
              />
            </div>
            
            {/* 模态框底部提示 */}
            <div className="fullscreen-modal-footer">
              <span className="shortcut-hint">
                <kbd>Enter</kbd> 发送 · <kbd>Shift+Enter</kbd> 换行 · <kbd>Esc</kbd> 关闭
              </span>
              <span className="char-count">{fullscreenText.length} 字符</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
};