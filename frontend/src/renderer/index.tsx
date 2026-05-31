/**
 * Luna AI 渲染进程入口
 * 负责：UI 渲染、Live2D 展示、状态展示、WebSocket 监听
 * 注意：渲染进程禁止直接访问本地 DB、Redis、Python 服务
 *
 * 架构原则：
 * 1. 主界面仅展示聊天界面，保持极简
 * 2. 左侧边栏提供导航菜单，点击菜单项打开居中模态窗口
 * 3. 所有状态来自 Go Runtime 推送，前端仅为状态投影
 * 4. 诊断面板 DebugPanel 独立渲染，与模态窗口互斥
 */
import React, { useEffect } from 'react';
import ReactDOM from 'react-dom/client';
import * as PIXI from 'pixi.js';
import { generateId } from '../shared/utils/snowflake';

// 导入全局样式
import './styles/global.css';

// 导入组件
import { ChatView } from './components/ChatView/ChatView';
import { Sidebar } from './components/Sidebar/Sidebar';
import { SidebarTrigger } from './components/SidebarTrigger/SidebarTrigger';
import { Modal } from './components/Modal/Modal';
import DebugPanel from './components/Settings/DebugPanel';

// 导入服务和 Store
import { wsManager } from './services/wsManager';
import { useSessionStore } from './stores/sessionStore';
import { useSystemStore } from './stores/systemStore';

// 挂载全局 PIXI，必须在任何 pixi-live2d-display 导入前完成
// @ts-ignore
window.PIXI = PIXI;

/**
 * 初始化全局异常监听
 * 捕获 React ErrorBoundary 无法捕获的异常（如 setTimeout、Promise rejection）
 */
function initGlobalErrorListeners(): void {
  // 捕获未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const systemStore = useSystemStore.getState();
    systemStore.addFrontendError({
      id: generateId(),
      timestamp: Date.now(),
      level: 'ERROR',
      source: 'global_promise',
      message: event.reason?.message || '未处理的 Promise 异常',
      stack: event.reason?.stack,
      trace_id: systemStore.currentTraceID || undefined,
    });
  });

  // 捕获全局 JS 运行时异常
  window.onerror = (message, source, lineno, colno, error): boolean => {
    const systemStore = useSystemStore.getState();
    systemStore.addFrontendError({
      id: generateId(),
      timestamp: Date.now(),
      level: 'CRITICAL',
      source: 'global_runtime',
      message: typeof message === 'string' ? message : '全局运行时异常',
      stack: error?.stack,
      trace_id: systemStore.currentTraceID || undefined,
    });
    // 返回 true 阻止默认浏览器错误处理
    return true;
  };
}

/**
 * Luna AI 主应用组件
 * 采用极简布局：主界面为纯聊天区，左侧边栏提供导航，模态窗口展示功能面板
 * DebugPanel 诊断面板独立于 Modal 渲染，二者互斥
 */
// eslint-disable-next-line react-refresh/only-export-components
const App: React.FC = () => {
  // 使用 Zustand hook 方式获取函数，确保引用稳定
  // 注意：Zustand 的 selector 返回的函数引用是稳定的，不会导致 useEffect 重复执行
  const setSessionId = useSessionStore((state) => state.setSessionId);
  const addSystemLog = useSystemStore((state) => state.addSystemLog);
  const isLeftSidebarOpen = useSystemStore((state) => state.isLeftSidebarOpen);
  const globalMessage = useSystemStore((state) => state.globalMessage);

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
      <main
        className="main-content"
        style={{
          marginLeft: isLeftSidebarOpen ? '260px' : '0',
          transition: 'margin-left 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        <ChatView />
      </main>

      {/* 左侧边栏开关按钮：固定在左上角 */}
      <SidebarTrigger />

      {/* 左侧边栏：提供导航菜单 */}
      <Sidebar />

      {/* 模态窗口：居中展示功能面板 */}
      <Modal />

      {/* 诊断面板：独立于模态窗口渲染，通过 isDiagnosticOpen 控制显隐 */}
      <DebugPanel />

      {/* 全局消息提示 */}
      {globalMessage && (
        <div className="global-message-toast">
          {globalMessage}
        </div>
      )}
    </div>
  );
};

// 初始化全局异常监听
initGlobalErrorListeners();

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
