/**
 * Luna AI 系统状态管理
 * 管理连接状态、侧边栏状态等系统级配置
 */
import { create } from 'zustand';

/**
 * 侧边栏面板类型
 */
export type SidebarPanelType = 'dag' | 'memory' | 'settings' | 'logs';

/**
 * WebSocket 连接状态
 */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

/**
 * 系统状态切片
 */
interface SystemState {
  // WebSocket 连接状态
  connectionStatus: ConnectionStatus;
  // 侧边栏是否展开
  isSidebarOpen: boolean;
  // 当前激活的侧边栏面板
  activeSidebarPanel: SidebarPanelType;
  // 系统日志（用于调试面板）
  systemLogs: string[];
  // 是否显示调试面板
  isDebugPanelOpen: boolean;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  openSidebar: (panel: SidebarPanelType) => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
  addSystemLog: (log: string) => void;
  clearSystemLogs: () => void;
  setDebugPanelOpen: (isOpen: boolean) => void;
}

/**
 * 创建系统状态 Store
 */
export const useSystemStore = create<SystemState>((set) => ({
  connectionStatus: 'disconnected',
  isSidebarOpen: false,
  activeSidebarPanel: 'dag',
  systemLogs: [],
  isDebugPanelOpen: false,

  // 设置连接状态
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  // 打开侧边栏并切换到指定面板
  openSidebar: (panel) => set({ isSidebarOpen: true, activeSidebarPanel: panel }),

  // 关闭侧边栏
  closeSidebar: () => set({ isSidebarOpen: false }),

  // 切换侧边栏展开状态
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),

  // 添加系统日志
  addSystemLog: (log) =>
    set((state) => ({
      systemLogs: [...state.systemLogs, `[${new Date().toLocaleTimeString()}] ${log}`],
    })),

  // 清空系统日志
  clearSystemLogs: () => set({ systemLogs: [] }),

  // 设置调试面板开关
  setDebugPanelOpen: (isOpen) => set({ isDebugPanelOpen: isOpen }),
}));