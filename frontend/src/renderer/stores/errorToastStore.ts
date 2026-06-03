/**
 * Luna AI 全局错误提示状态管理
 *
 * 做什么：管理 ErrorToast 组件所需的错误提示队列和显示状态。
 * 为什么这样做：将 UI 状态与组件逻辑分离，通过 Zustand 集中管理。
 * 边界条件：
 *   - 错误提示队列最多保留 50 条历史
 *   - 自动关闭时间默认为 6 秒，关闭动画结束后自动移除
 *   - 新错误自动追加到队列尾部，同源同内容的错误自动去重合并
 */
import { create } from 'zustand';

/** 错误提示条目结构 */
export interface ErrorToastItem {
  /** 唯一标识（Snowflake ID） */
  id: string;
  /** 错误级别 */
  level: 'ERROR' | 'WARN' | 'CRITICAL';
  /** 错误来源标识 */
  source: string;
  /** 错误摘要 */
  message: string;
  /** 详细错误信息（可选） */
  detail?: string;
  /** 关联的 TraceID */
  trace_id?: string;
  /** 创建时间戳 */
  timestamp: number;
  /** 是否正在退出动画中 */
  exiting: boolean;
}

/** ErrorToast 状态切片 */
interface ErrorToastState {
  /** 当前正在显示的错误提示列表（按时间正序排列） */
  toasts: ErrorToastItem[];
  /** 最大同时显示的提示数量 */
  maxVisible: number;

  /** 添加一条错误提示（同时触发持久化上报和前端 UI 展示） */
  addToast: (item: Omit<ErrorToastItem, 'exiting'>) => void;
  /** 标记指定提示为退出动画状态 */
  markExiting: (id: string) => void;
  /** 从队列中移除指定提示 */
  removeToast: (id: string) => void;
  /** 清空所有提示 */
  clearAll: () => void;
}

/** 默认自动关闭延迟（毫秒） */
export const ERROR_TOAST_DURATION = 6000;
/** 退出动画持续时间（毫秒） */
export const ERROR_TOAST_EXIT_DURATION = 500;
/** 最大可见提示数 */
export const MAX_VISIBLE_TOASTS = 3;
/** 提示条目历史最大保留数 */
export const MAX_TOAST_HISTORY = 50;

/**
 * 创建 ErrorToast Store
 */
export const useErrorToastStore = create<ErrorToastState>((set) => ({
  toasts: [],
  maxVisible: MAX_VISIBLE_TOASTS,

  addToast: (item) =>
    set((state) => {
      // 去重检查：同源同类同消息的提示不重复添加
      const isDuplicate = state.toasts.some(
        (t) =>
          !t.exiting &&
          t.level === item.level &&
          t.source === item.source &&
          t.message === item.message,
      );
      if (isDuplicate) {
        return state;
      }

      const newToast: ErrorToastItem = { ...item, exiting: false };
      const newToasts = [...state.toasts, newToast];

      // 限制历史上限
      if (newToasts.length > MAX_TOAST_HISTORY) {
        newToasts.splice(0, newToasts.length - MAX_TOAST_HISTORY);
      }

      return { toasts: newToasts };
    }),

  markExiting: (id) =>
    set((state) => ({
      toasts: state.toasts.map((t) =>
        t.id === id ? { ...t, exiting: true } : t,
      ),
    })),

  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),

  clearAll: () => set({ toasts: [] }),
}));

/**
 * 添加一条错误提示的便捷方法
 * 同时处理：UI 展示 + 自动关闭定时器
 *
 * 做什么：创建一条错误提示条目并添加到队列，返回后调用方可设置自动关闭定时器。
 * 为什么这样做：将创建与销毁逻辑分离，组件层负责定时关闭。
 * 输入：
 *   - level: 错误级别
 *   - source: 来源标识
 *   - message: 错误摘要
 *   - detail: 详细信息（可选）
 *   - trace_id: 关联 TraceID（可选）
 * 输出：创建的错误提示条目 ID
 */
export function createErrorToast(
  level: ErrorToastItem['level'],
  source: string,
  message: string,
  detail?: string,
  trace_id?: string,
): string {
  const id = crypto.randomUUID(); // 简化生成，仅用于 UI 标识
  const store = useErrorToastStore.getState();

  store.addToast({
    id,
    level,
    source,
    message,
    detail,
    trace_id,
    timestamp: Date.now(),
  });

  return id;
}
