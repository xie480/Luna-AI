/**
 * 渲染进程入口
 * 负责：UI 渲染、Live2D 展示、状态展示、WebSocket 监听
 * 注意：渲染进程禁止直接访问本地 DB、Redis、Python 服务
 */
import React, { useState, useEffect, useRef } from 'react';
import ReactDOM from 'react-dom/client';
import { WSMessage, PingPayload, PongPayload, ErrorPayload } from '../shared/types';

/**
 * 最小 App 根组件
 * Phase 1: 实现 WebSocket 客户端及 Ping/Pong UI
 */
const App: React.FC = () => {
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [messages, setMessages] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const connectWebSocket = () => {
    setWsStatus('connecting');
    // 假设 Go Runtime 运行在 8080 端口
    const ws = new WebSocket('ws://localhost:8080/ws');

    ws.onopen = () => {
      setWsStatus('connected');
      addMessage('WebSocket 已连接');
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        if (msg.type === 'PONG') {
          const payload = msg.payload as PongPayload;
          addMessage(`收到 PONG: trace_id=${msg.trace_id}, source=${payload.source}, timestamp=${payload.timestamp}`);
        } else if (msg.type === 'ERROR') {
          const payload = msg.payload as ErrorPayload;
          addMessage(`收到 ERROR: trace_id=${msg.trace_id}, code=${payload.code}, message=${payload.message}`);
        } else {
          addMessage(`收到未知消息: ${event.data}`);
        }
      } catch (e) {
        addMessage(`解析消息失败: ${event.data}`);
      }
    };

    ws.onclose = () => {
      setWsStatus('disconnected');
      addMessage('WebSocket 已断开连接');
      // 简单的重连机制
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (error) => {
      addMessage(`WebSocket 错误`);
    };

    wsRef.current = ws;
  };

  const addMessage = (msg: string) => {
    setMessages((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
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
      addMessage(`发送 PING: trace_id=${traceId}`);
    } else {
      addMessage('WebSocket 未连接，无法发送 PING');
    }
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h1>Luna AI - Phase 1</h1>
      <p>状态: {wsStatus}</p>
      <button 
        onClick={handlePing} 
        disabled={wsStatus !== 'connected'}
        style={{ padding: '8px 16px', marginBottom: '20px' }}
      >
        发送 Ping
      </button>
      
      <div style={{ 
        border: '1px solid #ccc', 
        padding: '10px', 
        height: '300px', 
        overflowY: 'auto',
        backgroundColor: '#f9f9f9'
      }}>
        {messages.map((msg, index) => (
          <div key={index} style={{ marginBottom: '4px', fontSize: '14px' }}>{msg}</div>
        ))}
      </div>
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
