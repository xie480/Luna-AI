/**
 * Luna AI 系统状态管理
 * 管理连接状态、左侧边栏状态、模态窗口状态等系统级配置
 */
import { create } from 'zustand';

/**
 * 模态窗口面板类型
 * 用于标识当前模态窗口展示的内容
 */
export type ModalPanelType = 'dag' | 'memory' | 'settings' | 'logs';

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
  // 左侧边栏是否展开
  isLeftSidebarOpen: boolean;
  // 模态窗口是否打开
  isModalOpen: boolean;
  // 当前模态窗口展示的面板类型
  activeModalPanel: ModalPanelType | null;
  // 系统日志（用于调试面板）
  systemLogs: string[];
  // 是否显示调试面板
  isDebugPanelOpen: boolean;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  toggleLeftSidebar: () => void;
  openLeftSidebar: () => void;
  closeLeftSidebar: () => void;
  openModal: (panel: ModalPanelType) => void;
  closeModal: () => void;
  addSystemLog: (log: string) => void;
  clearSystemLogs: () => void;
  setDebugPanelOpen: (isOpen: boolean) => void;
}

/**
 * 创建系统状态 Store
 */
export const useSystemStore = create<SystemState>((set) => ({
  connectionStatus: 'disconnected',
  isLeftSidebarOpen: false,
  isModalOpen: false,
  activeModalPanel: null,
  systemLogs: [],
  isDebugPanelOpen: false,

  // 设置连接状态
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  // 切换左侧边栏展开状态
  toggleLeftSidebar: () => set((state) => ({ isLeftSidebarOpen: !state.isLeftSidebarOpen })),

  // 打开左侧边栏
  openLeftSidebar: () => set({ isLeftSidebarOpen: true }),

  // 关闭左侧边栏
  closeLeftSidebar: () => set({ isLeftSidebarOpen: false }),

  // 打开模态窗口并展示指定面板
  openModal: (panel) => set({ isModalOpen: true, activeModalPanel: panel }),

  // 关闭模态窗口
  closeModal: () => set({ isModalOpen: false, activeModalPanel: null }),

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