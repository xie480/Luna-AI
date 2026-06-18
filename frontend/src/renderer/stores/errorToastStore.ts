/**
 * Luna AI 全局错误提示状态管理
 *
 * 做什么：管理 ErrorToast 组件所需的错误提示队列和显示状态。
 *        采用严格串行阻塞队列机制：一次只显示一条气泡，新气泡有序等待。
 *        当前气泡的 TTL 自然耗尽并完成离场动画后，才从队列提取下一个。
 * 为什么这样做：避免同时多个提示相互覆盖/挤占，使用户能逐一阅读每条消息。
 * 边界条件：
 *   - 错误提示队列最多保留 50 条历史
 *   - 自动关闭时间按文本长度动态计算（每字符 100ms，夹紧 [800ms, 3000ms]）
 *   - 关闭动画结束后自动移除，然后自动播放下一条
 *   - 新错误自动追加到队列尾部，同源同内容的错误自动去重合并
 *   - 用户手动点击关闭时立即标记退出，触发下一条调度
 */
import { create } from 'zustand';
import { generateId } from '../../shared/utils/snowflake';

/** 错误提示条目结构 */
export interface ErrorToastItem {
  /** 唯一标识（Snowflake ID） */
  id: string;
  /** 错误级别 */
  level: 'ERROR' | 'WARN' | 'CRITICAL' | 'INFO' | 'SUCCESS';
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
  /** 最大同时显示的提示数量（串行队列下固定为 1，保留字段供外部兼容） */
  maxVisible: number;
  /** 当前正在展示的气泡 ID（串行队列活跃项），null 表示无活跃气泡 */
  activeToastId: string | null;
  /** 串行处理器是否正在运行 */
  _isProcessing: boolean;

  /** 添加一条错误提示（入队，若空闲则立即触发串行调度） */
  addToast: (item: Omit<ErrorToastItem, 'exiting'>) => void;
  /** 标记指定提示为退出动画状态（手动关闭时调用） */
  markExiting: (id: string) => void;
  /** 从队列中移除指定提示（动画结束后调用） */
  removeToast: (id: string) => void;
  /** 清空所有提示和活跃状态 */
  clearAll: () => void;
  /** 内部：串行调度器，取出队列中下一个非退出态气泡进行渲染 */
  _processNext: () => void;
}

// ============================================================
// 常量定义
// ============================================================

/** 默认自动关闭延迟上限（毫秒），重构后作为动态 TTL 的最大值 */
export const ERROR_TOAST_DURATION = 3000;
/** 退出动画持续时间（毫秒） */
export const ERROR_TOAST_EXIT_DURATION = 500;
/** 最大可见提示数（串行队列下固定为 1，保留字段供外部兼容引用） */
export const MAX_VISIBLE_TOASTS = 1;
/** 提示条目历史最大保留数 */
export const MAX_TOAST_HISTORY = 50;

/** 每字符基础驻留时间（毫秒），用于按文本长度正比例计算 TTL。 */
const BASE_TTL_PER_CHAR = 100;
/** 最小驻留时间（毫秒），确保极短文本也有足够的阅读时间。 */
const MIN_TTL = 800;
/** 最大驻留时间（毫秒），重构后保证最多 3 秒。 */
const MAX_TTL = 3000;
/** 兜底 TTL（文本为空时）。 */
const FALLBACK_TTL = 800;

/**
 * 动态计算错误提示气泡的驻留时间（TTL）。
 *
 * 做什么：严格按文本长度（message + (detail||'')）成比例计算存活时长。
 * 为什么这样做：短错误只需一瞥认识，长错误需要完整阅读时间。
 * 公式：clamp(totalLength × BASE_TTL_PER_CHAR, MIN_TTL, MAX_TTL)
 *       每字符 100ms：8 字 → 800ms，20 字 → 2000ms，30 字及以上 → 3000ms（上限）
 * 边界条件：空文本返回 FALLBACK_TTL 兜底。
 */
function calculateToastTTL(item: Pick<ErrorToastItem, 'message' | 'detail'>): number {
  const totalLength = (item.message || '').length + (item.detail || '').length;
  if (totalLength === 0) return FALLBACK_TTL;
  return Math.min(Math.max(totalLength * BASE_TTL_PER_CHAR, MIN_TTL), MAX_TTL);
}

/**
 * 创建 ErrorToast Store
 */
export const useErrorToastStore = create<ErrorToastState>((set, get) => ({
  toasts: [],
  maxVisible: MAX_VISIBLE_TOASTS,
  activeToastId: null,
  _isProcessing: false,

  addToast: (item) => {
    // 去重检查：同源同类同消息的提示不重复添加
    const state = get();
    const isDuplicate = state.toasts.some(
      (t) =>
        !t.exiting &&
        t.level === item.level &&
        t.source === item.source &&
        t.message === item.message,
    );
    if (isDuplicate) return;

    const newToast: ErrorToastItem = { ...item, exiting: false };

    set((prevState) => {
      const newToasts = [...prevState.toasts, newToast];
      // 限制历史上限
      if (newToasts.length > MAX_TOAST_HISTORY) {
        newToasts.splice(0, newToasts.length - MAX_TOAST_HISTORY);
      }
      return { toasts: newToasts };
    });

    // 如果串行处理器未运行，立即启动
    if (!get()._isProcessing) {
      get()._processNext();
    }
  },

  markExiting: (id) => {
    set((state) => ({
      toasts: state.toasts.map((t) =>
        t.id === id ? { ...t, exiting: true } : t,
      ),
    }));

    // 如果标记退出的正是当前活跃气泡，且处理器未运行，重新触发调度
    const currentState = get();
    if (currentState.activeToastId === id && !currentState._isProcessing) {
      currentState._processNext();
    }
  },

  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
      activeToastId: state.activeToastId === id ? null : state.activeToastId,
    }));

    // 移除后如果处理器未运行，则启动调度下一个
    if (!get()._isProcessing) {
      get()._processNext();
    }
  },

  clearAll: () => {
    set({ toasts: [], activeToastId: null, _isProcessing: false });
  },

  _processNext: () => {
    const { toasts, activeToastId, _isProcessing } = get();

    // 防止重复进入
    if (_isProcessing) return;

    // 查找队列中第一个非退出态、且不是当前活跃项的气泡
    const nextItem = toasts.find(
      (t) => !t.exiting && t.id !== activeToastId,
    );
    if (!nextItem) {
      set({ _isProcessing: false });
      return;
    }

    // 标记处理器为运行中，并设置当前活跃气泡 ID
    set({ _isProcessing: true, activeToastId: nextItem.id });

    // 动态计算 TTL（严格按文本长度正比例，最多 3 秒）
    const ttl = calculateToastTTL(nextItem);

    // 第一阶段：TTL 自然耗尽
    setTimeout(() => {
      const stateAfterTTL = get();
      const toastStillActive = stateAfterTTL.toasts.find(
        (t) => t.id === nextItem.id && !t.exiting,
      );
      // 如果气泡已被手动关闭（exiting），跳过自动关闭逻辑
      if (!toastStillActive) {
        // 气泡已被手动处理，直接调度下一个
        set({ activeToastId: null, _isProcessing: false });
        get()._processNext();
        return;
      }

      // 标记为退出动画状态
      set({
        toasts: stateAfterTTL.toasts.map((t) =>
          t.id === nextItem.id ? { ...t, exiting: true } : t,
        ),
      });

      // 第二阶段：等待离场动画完成后，移除气泡并调度下一个
      setTimeout(() => {
        const stateAfterExit = get();
        set({
          toasts: stateAfterExit.toasts.filter((t) => t.id !== nextItem.id),
          activeToastId: null,
          _isProcessing: false,
        });
        // 递归调度下一个气泡
        get()._processNext();
      }, ERROR_TOAST_EXIT_DURATION);
    }, ttl);
  },
}));

/**
 * 添加一条错误提示的便捷方法
 * 同时处理：UI 展示 + 自动关闭定时器
 *
 * 做什么：创建一条错误提示条目并添加到队列，由串行调度器负责展示和自动关闭。
 * 为什么这样做：将创建与销毁逻辑收口到 Store 内部统一管理，组件层只负责渲染。
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
  const id = generateId();
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
