/**
 * 渲染进程入口
 * 负责：UI 渲染、Live2D 展示、状态展示、WebSocket 监听
 * 注意：渲染进程禁止直接访问本地 DB、Redis、Python 服务
 */
import React from 'react';
import ReactDOM from 'react-dom/client';

/**
 * 最小 App 根组件
 * Phase 0 仅展示基础 UI 框架，后续阶段逐步扩展
 */
const App: React.FC = () => {
  return (
    <div style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h1>Luna AI</h1>
      <p>本地优先、隐私安全的 AI 桌面助理</p>
      <p>Phase 0: 工程规范与运行基线已就绪</p>
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
