/**
 * Luna AI 系统状态管理
 * 管理连接状态、左侧边栏状态、模态窗口状态等系统级配置
 */
import { create } from 'zustand';
import { CHAT_MODE, TTS_LANGUAGE } from '../../shared/enum';
import type { ChatMode } from '../../shared/types';
import { EMOTION_EXPRESSIONS } from '../constants/emotionExpressions';

/**
 * 模态窗口面板类型
 * 用于标识当前模态窗口展示的内容
 */
export type ModalPanelType = 'dag' | 'memory' | 'userProfile' | 'prompts' | 'knowledge' | 'settings' | 'logs' | 'clothing' | 'mcp';

/**
 * 连接状态（SSE / HTTP）
 */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

/**
 * 情绪状态 (ESM)
 * 用于驱动 Live2D 表情与动作
 */
export type EmotionState = keyof typeof EMOTION_EXPRESSIONS | 'neutral';

/**
 * 前端异常条目
 * 用于记录前端运行时异常，供诊断面板查阅
 */
export interface FrontendErrorEntry {
  id: string;            // Snowflake ID
  timestamp: number;
  level: 'ERROR' | 'WARN' | 'CRITICAL';
  source: string;        // 异常来源，如 'react_renderer', 'websocket', 'live2d'
  message: string;
  stack?: string;
  trace_id?: string;     // 关联的 TraceID
  component_stack?: string; // React 组件栈（Error Boundary 捕获）
}

/**
 * 系统状态切片
 */
interface SystemState {
  // 连接状态（SSE / HTTP）
  connectionStatus: ConnectionStatus;
  // AI 服务连接状态
  aiConnectionStatus: ConnectionStatus;
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
  // 服装配置状态（实时保存到 localStorage）
  clothingConfig: Record<string, boolean>;
  // Live2D 渲染开关
  isLive2dEnabled: boolean;
  // 本地 TTS 语音开关
  isTTSEnabled: boolean;
  // LLM 响应模式：unified（统一非流式，默认） / streaming（传统流式兼容）
  llmResponseMode: 'unified' | 'streaming';
  // Live2D 空闲降频开关
  isLive2dIdleThrottlingEnabled: boolean;
  // Live2D 后台挂起开关
  isLive2dBackgroundSuspensionEnabled: boolean;
  // Live2D 最大帧率
  live2dMaxFPS: 30 | 60 | 90 | 120;
  // 是否展示气泡渲染（默认开启）
  showBubbleRender: boolean;
  // TTS 语言选项
  ttsLanguage: string;
  // 主题设置
  theme: 'dark' | 'light' | 'cyberpunk';
  /**
   * 当前聊天模式。
   * 做什么：控制输入框左侧胶囊切换器的模式状态。
   * 为什么这样做：聊天模式影响后端 Prompt 装配与工作流行为，前端需持久化用户偏好。
   * 边界条件：默认 DAILY_CHAT（深度日常助理），切换后持久化到 localStorage。
   */
  chatMode: ChatMode;
  
  // 回答模式
  answerMode: 'short' | 'long';

  // === 可观测性相关增强 ===
  // 前端异常缓冲区（环形缓冲，最多保留 100 条）
  frontendErrors: FrontendErrorEntry[];
  // 诊断面板是否打开（与独立调试面板联动）
  isDiagnosticOpen: boolean;
  // 当前 TraceID（由 sseManager 自动维护，用于异常上报关联）
  currentTraceID: string | null;
  // 后端服务是否完全就绪
  isBackendReady: boolean;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  setAiConnectionStatus: (status: ConnectionStatus) => void;
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
  // 设置服装配置项，同时持久化到 localStorage
  setClothingConfig: (id: string, enabled: boolean) => void;
  // 设置 Live2D 渲染开关
  setLive2dEnabled: (enabled: boolean) => void;
  // 设置 本地 TTS 语音开关
  setTTSEnabled: (enabled: boolean) => void;
  // 设置 TTS 语言选项
  setTTSLanguage: (lang: string) => void;
  // 设置 LLM 响应模式
  setLlmResponseMode: (mode: 'unified' | 'streaming') => void;
  // 设置 Live2D 空闲降频开关
  setLive2dIdleThrottlingEnabled: (enabled: boolean) => void;
  // 设置 Live2D 后台挂起开关
  setLive2dBackgroundSuspensionEnabled: (enabled: boolean) => void;
  // 设置 Live2D 最大帧率
  setLive2dMaxFPS: (fps: 30 | 60 | 90 | 120) => void;
  // 设置气泡渲染开关
  setShowBubbleRender: (enabled: boolean) => void;
  // 设置主题
  setTheme: (theme: 'dark' | 'light' | 'cyberpunk') => void;
  /**
   * 设置聊天模式。
   * 做什么：切换日常助理/极速闲聊模式，并持久化到 localStorage。
   */
  setChatMode: (mode: ChatMode) => void;
  // 设置回答模式（短/长）
  setAnswerMode: (mode: 'short' | 'long') => void;

  // 可观测性 Actions
  addFrontendError: (entry: FrontendErrorEntry) => void;
  clearFrontendErrors: () => void;
  setDiagnosticOpen: (isOpen: boolean) => void;
  setCurrentTraceID: (traceId: string | null) => void;
  setBackendReady: (isReady: boolean) => void;
}

/**
 * 从 localStorage 读取服装配置，不存在时返回空对象
 * 服装项由 ClothingPanel 动态扫描目录后决定，这里不写死默认值
 */
function loadClothingConfig(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem('luna:clothing');
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回空对象
  }
  return {};
}

function loadLive2dEnabled(): boolean {
  try {
    const raw = localStorage.getItem('luna:live2dEnabled');
    if (raw !== null) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return true; // 默认开启
}

function loadTTSEnabled(): boolean {
  try {
    const raw = localStorage.getItem('luna:ttsEnabled');
    if (raw !== null) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return true; // 默认开启
}

function loadLive2dIdleThrottlingEnabled(): boolean {
  try {
    const raw = localStorage.getItem('luna:live2dIdleThrottlingEnabled');
    if (raw !== null) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return true; // 默认开启
}

function loadLive2dBackgroundSuspensionEnabled(): boolean {
  try {
    const raw = localStorage.getItem('luna:live2dBackgroundSuspensionEnabled');
    if (raw !== null) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return true; // 默认开启
}

function loadLive2dMaxFPS(): 30 | 60 | 90 | 120 {
  try {
    const raw = localStorage.getItem('luna:live2dMaxFPS');
    if (raw !== null) {
      const fps = parseInt(raw, 10);
      if (fps === 30 || fps === 60 || fps === 90 || fps === 120) {
        return fps;
      }
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return 60; // 默认 60 FPS
}

function loadShowBubbleRender(): boolean {
  try {
    const raw = localStorage.getItem('luna:showBubbleRender');
    if (raw !== null) {
      return JSON.parse(raw);
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return true; // 默认开启
}

function loadTTSLanguage(): string {
  try {
    const raw = localStorage.getItem('luna:ttsLanguage');
    if (raw === TTS_LANGUAGE.ZH || raw === TTS_LANGUAGE.JA) {
      return raw;
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return TTS_LANGUAGE.ZH; // 默认中文
}

function loadTheme(): 'dark' | 'light' | 'cyberpunk' {
  try {
    const raw = localStorage.getItem('luna:theme');
    if (raw === 'dark' || raw === 'light' || raw === 'cyberpunk') {
      return raw as 'dark' | 'light' | 'cyberpunk';
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return 'dark'; // 默认暗色，避免强制切换
}

/**
 * 从 localStorage 读取聊天模式，不存在时返回默认深度日常助理模式。
 * 为什么这样做：用户偏好应跨会话持久化，避免每次启动都重置为默认值。
 */
/**
 * 从 localStorage 读取聊天模式，不存在时返回默认深度日常助理模式。
 * 为什么这样做：用户偏好应跨会话持久化，避免每次启动都重置为默认值。
 * 边界条件：新增模式时必须在此处同步添加校验，否则切换后重启会丢失偏好。
 */
function loadChatMode(): ChatMode {
  try {
    const raw = localStorage.getItem('luna:chatMode');
    if (
      raw === CHAT_MODE.DAILY_CHAT ||
      raw === CHAT_MODE.CASUAL_CHAT ||
      raw === CHAT_MODE.PLAN_STATE_NODE ||
      raw === CHAT_MODE.AGENT_LOOP
    ) {
      return raw as ChatMode;
    }
  } catch (e) {
    // 解析失败时返回默认值
  }
  return CHAT_MODE.DAILY_CHAT;
}

/**
 * 创建系统状态 Store
 */
export const useSystemStore = create<SystemState>((set) => ({
  connectionStatus: 'disconnected',
  aiConnectionStatus: 'disconnected',
  isLeftSidebarOpen: false,
  isModalOpen: false,
  activeModalPanel: null,
  systemLogs: [],
  isDebugPanelOpen: false,
  currentEmotion: 'neutral',
  live2dConfigMode: 'none',
  globalMessage: null,
  // 初始化服装配置，从 localStorage 读取或使用空对象
  clothingConfig: loadClothingConfig(),
  isLive2dEnabled: loadLive2dEnabled(),
  isTTSEnabled: loadTTSEnabled(),
  // LLM 响应模式默认使用 unified（统一非流式），可从 localStorage 恢复用户偏好
  llmResponseMode: (localStorage.getItem('luna:llmResponseMode') as 'unified' | 'streaming') || 'unified',
  isLive2dIdleThrottlingEnabled: loadLive2dIdleThrottlingEnabled(),
  isLive2dBackgroundSuspensionEnabled: loadLive2dBackgroundSuspensionEnabled(),
  live2dMaxFPS: loadLive2dMaxFPS(),
  showBubbleRender: loadShowBubbleRender(),
  ttsLanguage: loadTTSLanguage(),
  theme: loadTheme(),
  // 聊天模式，从 localStorage 恢复用户偏好，默认深度日常助理
  chatMode: loadChatMode(),
  // 回答模式：默认短回答
  answerMode: (localStorage.getItem('luna:answerMode') as 'short' | 'long') || 'short',
  // 可观测性初始状态
  frontendErrors: [],
  isDiagnosticOpen: false,
  currentTraceID: null,
  isBackendReady: false,

  // 设置连接状态
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  // 设置 AI 服务连接状态
  setAiConnectionStatus: (status) => set({ aiConnectionStatus: status }),

  // 切换左侧边栏展开状态
  toggleLeftSidebar: () => set((state) => ({ isLeftSidebarOpen: !state.isLeftSidebarOpen })),

  // 打开左侧边栏
  openLeftSidebar: () => set({ isLeftSidebarOpen: true }),

  // 关闭左侧侧边栏
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

  // 设置服装配置项，同时持久化到 localStorage
  setClothingConfig: (id, enabled) =>
    set((state) => {
      const newConfig = { ...state.clothingConfig, [id]: enabled };
      try {
        localStorage.setItem('luna:clothing', JSON.stringify(newConfig));
      } catch (e) {
        // 忽略存储错误（如 localStorage 满）
      }
      return { clothingConfig: newConfig };
    }),

  setLive2dEnabled: (enabled) =>
    set(() => {
      try {
        localStorage.setItem('luna:live2dEnabled', JSON.stringify(enabled));
      } catch (e) {
        // 忽略存储错误
      }
      return { isLive2dEnabled: enabled };
    }),

  setTTSEnabled: (enabled) =>
    set(() => {
      try {
        localStorage.setItem('luna:ttsEnabled', JSON.stringify(enabled));
      } catch (e) {
        // 忽略存储错误
      }
      return { isTTSEnabled: enabled };
    }),

  // 设置 LLM 响应模式，同时持久化到 localStorage 以便跨会话保留用户偏好
  setLlmResponseMode: (mode) =>
    set(() => {
      try {
        localStorage.setItem('luna:llmResponseMode', mode);
      } catch (e) {
        // 忽略存储错误
      }
      return { llmResponseMode: mode };
    }),

  setLive2dIdleThrottlingEnabled: (enabled) =>
    set(() => {
      try {
        localStorage.setItem('luna:live2dIdleThrottlingEnabled', JSON.stringify(enabled));
      } catch (e) {
        // 忽略存储错误
      }
      return { isLive2dIdleThrottlingEnabled: enabled };
    }),

  setLive2dBackgroundSuspensionEnabled: (enabled) =>
    set(() => {
      try {
        localStorage.setItem('luna:live2dBackgroundSuspensionEnabled', JSON.stringify(enabled));
      } catch (e) {
        // 忽略存储错误
      }
      return { isLive2dBackgroundSuspensionEnabled: enabled };
    }),

  setLive2dMaxFPS: (fps) =>
    set(() => {
      try {
        localStorage.setItem('luna:live2dMaxFPS', fps.toString());
      } catch (e) {
        // 忽略存储错误
      }
      return { live2dMaxFPS: fps };
    }),

  setShowBubbleRender: (enabled) =>
    set(() => {
      try {
        localStorage.setItem('luna:showBubbleRender', JSON.stringify(enabled));
      } catch (e) {
        // 忽略存储错误
      }
      return { showBubbleRender: enabled };
    }),

  setTTSLanguage: (lang) =>
    set(() => {
      try {
        localStorage.setItem('luna:ttsLanguage', lang);
      } catch (e) {
        // 忽略存储错误
      }
      return { ttsLanguage: lang };
    }),

  setTheme: (theme) =>
    set(() => {
      try {
        localStorage.setItem('luna:theme', theme);
        // 动态修改 body 的 class 或 data 属性以应用主题
        document.documentElement.setAttribute('data-theme', theme);
      } catch (e) {
        // 忽略存储错误
      }
      return { theme };
    }),

  /**
   * 设置聊天模式并持久化到 localStorage。
   * 做什么：切换日常助理/极速闲聊模式，用户偏好跨会话保留。
   * 为什么这样做：用户对模式的选择应当持久化，避免每次重启重置。
   */
  setChatMode: (mode) =>
    set(() => {
      try {
        localStorage.setItem('luna:chatMode', mode);
      } catch (e) {
        // 忽略存储错误（如 localStorage 满）
      }
      return { chatMode: mode };
    }),

  setAnswerMode: (mode) =>
    set(() => {
      try {
        localStorage.setItem('luna:answerMode', mode);
      } catch (e) {
        // 忽略存储错误
      }
      return { answerMode: mode };
    }),

  // 添加前端异常（环形缓冲，最多 100 条）
  addFrontendError: (entry) =>
    set((state) => {
      const newErrors = [...state.frontendErrors, entry];
      if (newErrors.length > 100) {
        newErrors.shift(); // 移除最旧的一条
      }
      return { frontendErrors: newErrors };
    }),

  // 清空前端异常
  clearFrontendErrors: () => set({ frontendErrors: [] }),

  // 设置诊断面板开关
  setDiagnosticOpen: (isOpen) => set({ isDiagnosticOpen: isOpen }),

  // 设置当前 TraceID
  setCurrentTraceID: (traceId) => set({ currentTraceID: traceId }),

  // 设置后端就绪状态
  setBackendReady: (isReady) => set({ isBackendReady: isReady }),
}));
