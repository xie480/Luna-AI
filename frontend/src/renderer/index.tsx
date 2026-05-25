/**
 * Luna AI 渲染进程入口
 * 负责：UI 渲染、Live2D 展示、状态展示、WebSocket 监听
 * 注意：渲染进程禁止直接访问本地 DB、Redis、Python 服务
 * 
 * 架构原则：
 * 1. 主界面仅展示聊天界面，保持极简
 * 2. 其他界面（DAG 任务树、记忆面板、设置）通过侧边栏呼出
 * 3. 所有状态来自 Go Runtime 推送，前端仅为状态投影
 */
import React, { useEffect } from 'react';
import ReactDOM from 'react-dom/client';

// 导入全局样式
import './styles/global.css';

// 导入组件
import { ChatView } from './components/ChatView/ChatView';
import { Sidebar } from './components/Sidebar/Sidebar';
import { SidebarTrigger } from './components/SidebarTrigger/SidebarTrigger';

// 导入服务和 Store
import { wsManager } from './services/wsManager';
import { useSessionStore } from './stores/sessionStore';
import { useSystemStore } from './stores/systemStore';

/**
 * Luna AI 主应用组件
 * 采用极简布局：主界面为纯聊天区，侧边栏呼出其他功能
 */
// eslint-disable-next-line react-refresh/only-export-components
const App: React.FC = () => {
  // 使用 Zustand hook 方式获取函数，确保引用稳定
  // 注意：Zustand 的 selector 返回的函数引用是稳定的，不会导致 useEffect 重复执行
  const setSessionId = useSessionStore((state) => state.setSessionId);
  const addSystemLog = useSystemStore((state) => state.addSystemLog);

  /**
   * 应用启动时建立 WebSocket 连接
   * 并初始化默认会话
   *
   * 依赖数组为空数组，因为我们只需要在组件挂载时执行一次
   * setSessionId 和 addSystemLog 是 Zustand store 的 action，引用稳定
   */
  useEffect(() => {
    // 初始化默认会话 ID
    setSessionId('default-session');

    // 建立 WebSocket 连接
    wsManager.connect(8080);
    addSystemLog('应用启动，正在连接 Go Runtime...');

    // 清理函数：断开 WebSocket 连接
    return () => {
      wsManager.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app-container">
      {/* 主界面：纯聊天界面，占据全部空间 */}
      <main className="main-content">
        <ChatView />
      </main>

      {/* 侧边栏呼出按钮：悬浮在右上角 */}
      <SidebarTrigger />

      {/* 侧边栏：用于展示 DAG 任务树、记忆面板、设置等 */}
      <Sidebar />
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