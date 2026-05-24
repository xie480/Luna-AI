/**
 * 渲染进程入口
 * 负责：UI 渲染、Live2D 展示、状态展示、WebSocket 监听
 * 注意：渲染进程禁止直接访问本地 DB、Redis、Python 服务
 */
import React, { useState, useEffect, useRef } from 'react';
import ReactDOM from 'react-dom/client';
import { WSMessage, PingPayload, PongPayload, ErrorPayload, ChatRequestPayload, ChatStreamPayload } from '../shared/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isFinished: boolean;
  error?: string;
}

/**
 * 最小 App 根组件
 * Phase 2: 实现基础流式问答能力
 */
// eslint-disable-next-line react-refresh/only-export-components
const App: React.FC = () => {
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [systemLogs, setSystemLogs] = useState<string[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [healthData, setHealthData] = useState<any>(null);
  
  // 聊天相关状态
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  const connectWebSocket = React.useCallback(() => {
    setWsStatus('connecting');
    // 假设 Go Runtime 运行在 8080 端口
    const ws = new WebSocket('ws://localhost:8080/ws');

    ws.onopen = () => {
      setWsStatus('connected');
      addSystemLog('WebSocket 已连接');
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        if (msg.type === 'PONG') {
          const payload = msg.payload as PongPayload;
          addSystemLog(`收到 PONG: trace_id=${msg.trace_id}, source=${payload.source}, timestamp=${payload.timestamp}`);
        } else if (msg.type === 'ERROR') {
          const payload = msg.payload as ErrorPayload;
          addSystemLog(`收到 ERROR: trace_id=${msg.trace_id}, code=${payload.code}, message=${payload.message}`);
        } else if (msg.type === 'CHAT_STREAM') {
          const payload = msg.payload as ChatStreamPayload;
          handleChatStream(payload);
        } else {
          addSystemLog(`收到未知消息: ${event.data}`);
        }
      } catch (e) {
        addSystemLog(`解析消息失败: ${event.data}`);
      }
    };

    ws.onclose = () => {
      setWsStatus('disconnected');
      addSystemLog('WebSocket 已断开连接');
      // 简单的重连机制
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
      addSystemLog(`WebSocket 错误`);
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connectWebSocket]);

  const addSystemLog = (msg: string) => {
    setSystemLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const handleChatStream = (payload: ChatStreamPayload) => {
    setChatMessages((prev) => {
      const newMessages = [...prev];
      const lastMessage = newMessages[newMessages.length - 1];
      
      if (lastMessage && lastMessage.id === payload.node_id) {
        // 更新现有消息
        lastMessage.content += payload.chunk;
        lastMessage.isFinished = payload.is_finished;
        if (payload.error) {
          lastMessage.error = payload.error;
        }
      } else {
        // 创建新消息
        newMessages.push({
          id: payload.node_id,
          role: 'assistant',
          content: payload.chunk,
          isFinished: payload.is_finished,
          error: payload.error
        });
      }
      
      if (payload.is_finished) {
        setIsGenerating(false);
      }
      
      return newMessages;
    });
  };

  const handlePing = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const traceId = `req-${Date.now()}`;
      const payload: PingPayload = { timestamp: Date.now() };
      const msg: WSMessage = {
        type: 'PING',
        trace_id: traceId,
        payload: payload,
      };
      wsRef.current.send(JSON.stringify(msg));
      addSystemLog(`发送 PING: trace_id=${traceId}`);
    } else {
      addSystemLog('WebSocket 未连接，无法发送 PING');
    }
  };

  const handleSendMessage = () => {
    if (!inputValue.trim() || isGenerating) return;
    
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const traceId = `chat-${Date.now()}`;
      const payload: ChatRequestPayload = { message: inputValue };
      const msg: WSMessage = {
        type: 'CHAT_REQUEST',
        trace_id: traceId,
        payload: payload,
      };
      
      // 添加用户消息到 UI
      setChatMessages(prev => [...prev, {
        id: `user-${Date.now()}`,
        role: 'user',
        content: inputValue,
        isFinished: true
      }]);
      
      wsRef.current.send(JSON.stringify(msg));
      setInputValue('');
      setIsGenerating(true);
      addSystemLog(`发送 CHAT_REQUEST: trace_id=${traceId}`);
    } else {
      addSystemLog('WebSocket 未连接，无法发送消息');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const checkHealth = async () => {
    try {
      const response = await fetch('http://localhost:8080/health', {
        headers: {
          'X-Trace-ID': `req-${Date.now()}`
        }
      });
      const data = await response.json();
      setHealthData(data);
      addSystemLog(`健康检查结果: ${data.data.status}`);
    } catch (error) {
      addSystemLog(`健康检查失败: ${error}`);
    }
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif', display: 'flex', gap: '20px', height: '100vh', boxSizing: 'border-box' }}>
      {/* 左侧：聊天区域 */}
      <div style={{ flex: 2, display: 'flex', flexDirection: 'column', border: '1px solid #ccc', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{ padding: '15px', backgroundColor: '#f0f0f0', borderBottom: '1px solid #ccc' }}>
          <h2 style={{ margin: 0 }}>Luna AI Chat</h2>
          <span style={{ fontSize: '12px', color: wsStatus === 'connected' ? 'green' : 'red' }}>
            {wsStatus === 'connected' ? '● 已连接' : '○ 未连接'}
          </span>
        </div>
        
        <div style={{ flex: 1, padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '15px' }}>
          {chatMessages.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', marginTop: '50px' }}>
              开始与 Luna 对话吧...
            </div>
          ) : (
            chatMessages.map((msg) => (
              <div key={msg.id} style={{
                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth: '80%',
                display: 'flex',
                flexDirection: 'column'
              }}>
                <div style={{
                  backgroundColor: msg.role === 'user' ? '#007bff' : '#f1f1f1',
                  color: msg.role === 'user' ? 'white' : 'black',
                  padding: '10px 15px',
                  borderRadius: '15px',
                  borderBottomRightRadius: msg.role === 'user' ? '0' : '15px',
                  borderBottomLeftRadius: msg.role === 'assistant' ? '0' : '15px',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word'
                }}>
                  {msg.content}
                  {!msg.isFinished && msg.role === 'assistant' && (
                    <span style={{ display: 'inline-block', width: '8px', height: '15px', backgroundColor: '#666', marginLeft: '4px', animation: 'blink 1s step-end infinite' }}></span>
                  )}
                </div>
                {msg.error && (
                  <div style={{ color: 'red', fontSize: '12px', marginTop: '4px' }}>
                    错误: {msg.error}
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>
        
        <div style={{ padding: '15px', borderTop: '1px solid #ccc', display: 'flex', gap: '10px' }}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息..."
            disabled={wsStatus !== 'connected' || isGenerating}
            style={{ flex: 1, padding: '10px', borderRadius: '4px', border: '1px solid #ccc' }}
          />
          <button
            onClick={handleSendMessage}
            disabled={wsStatus !== 'connected' || isGenerating || !inputValue.trim()}
            style={{ padding: '10px 20px', borderRadius: '4px', backgroundColor: '#007bff', color: 'white', border: 'none', cursor: 'pointer' }}
          >
            发送
          </button>
        </div>
      </div>
      
      {/* 右侧：系统控制与日志 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '15px' }}>
          <h3>系统控制</h3>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button onClick={handlePing} disabled={wsStatus !== 'connected'}>发送 Ping</button>
            <button onClick={checkHealth}>检查健康状态</button>
          </div>
          {healthData && (
            <pre style={{ marginTop: '10px', backgroundColor: '#f0f0f0', padding: '10px', borderRadius: '4px', fontSize: '12px', overflowX: 'auto' }}>
              {JSON.stringify(healthData, null, 2)}
            </pre>
          )}
        </div>
        
        <div style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '15px', flex: 1, display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ marginTop: 0 }}>系统日志</h3>
          <div style={{
            flex: 1,
            overflowY: 'auto',
            backgroundColor: '#1e1e1e',
            color: '#00ff00',
            padding: '10px',
            borderRadius: '4px',
            fontFamily: 'monospace',
            fontSize: '12px'
          }}>
            {systemLogs.map((log, index) => (
              <div key={index} style={{ marginBottom: '4px' }}>{log}</div>
            ))}
          </div>
        </div>
      </div>
      
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  );
};

// 挂载 React 应用到 DOM
const rootElement = document.getElementById('root');
if (rootElement) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
