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
 * 情绪状态 (ESM)
 * 用于驱动 Live2D 表情与动作
 */
export type EmotionState = 'neutral' | 'happy' | 'sad' | 'angry' | 'thinking' | 'surprised';

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
  // 当前情绪状态
  currentEmotion: EmotionState;
  // Live2D 配置模式
  live2dConfigMode: 'none' | 'transform' | 'tracking';
  // 全局提示消息
  globalMessage: string | null;

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
  setEmotion: (emotion: EmotionState) => void;
  setLive2dConfigMode: (mode: 'none' | 'transform' | 'tracking') => void;
  showGlobalMessage: (message: string, duration?: number) => void;
  hideGlobalMessage: () => void;
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
  currentEmotion: 'neutral',
  live2dConfigMode: 'none',
  globalMessage: null,

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

  // 设置情绪状态
  setEmotion: (emotion) => set({ currentEmotion: emotion }),

  // 设置 Live2D 配置模式
  setLive2dConfigMode: (mode) => set({ live2dConfigMode: mode }),

  // 显示全局提示消息
  showGlobalMessage: (message, duration = 3000) => {
    set({ globalMessage: message });
    if (duration > 0) {
      setTimeout(() => {
        set((state) => {
          if (state.globalMessage === message) {
            return { globalMessage: null };
          }
          return state;
        });
      }, duration);
    }
  },

  // 隐藏全局提示消息
  hideGlobalMessage: () => set({ globalMessage: null }),
}));
