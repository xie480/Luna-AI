import { create } from 'zustand';

export interface VisualStateItem {
  id: string; // 唯一标识（通常用 traceId + stage）
  stage: string;
  state: 'RUNNING' | 'COMPLETED' | 'ERROR';
  text: string;
  isTerminal?: boolean; // 是否是结束节点（用于触发离场/折叠动画）
  colorTheme?: 'blue' | 'purple' | 'red' | 'cyan'; // 动态主题色
}

interface VisualStatusQueueState {
  queue: VisualStateItem[];
  currentVisualState: VisualStateItem | null;
  isProcessing: boolean;
  enqueue: (item: VisualStateItem) => void;
  processQueue: () => void;
  _popNext: () => void;
}

const MIN_DWELL_TIME = 800; // 核心防跳跃机制：强制驻留 800ms
const WARP_SPEED_THRESHOLD = 3; // 队列拥塞阈值
const WARP_DWELL_TIME = 200; // 曲率加速模式下的驻留时间

export const useVisualStatusQueue = create<VisualStatusQueueState>((set, get) => ({
  queue: [],
  currentVisualState: null,
  isProcessing: false,

  enqueue: (item) => {
    // 过滤空文案的静默状态（除非是 Terminal 节点用来清理）
    if (!item.text && !item.isTerminal) return;

    set((state) => ({ queue: [...state.queue, item] }));
    
    // 如果队列当前处于空闲，立刻启动处理循环
    if (!get().isProcessing) {
      get().processQueue();
    }
  },

  processQueue: () => {
    const { queue, _popNext } = get();
    if (queue.length === 0) {
      set({ isProcessing: false });
      // 可以在此处设置 currentVisualState = null 或特定的 Idle 状态
      return;
    }

    set({ isProcessing: true });
    _popNext();
  },

  _popNext: () => {
    const { queue } = get();
    if (queue.length === 0) {
      get().processQueue(); // 递归回入口，结束 processing
      return;
    }

    // 状态修剪 (State Pruning): 如果积压极度严重，丢弃中间过渡态，直接跳到最新的核心态
    let nextItem = queue[0];
    let remainingQueue = queue.slice(1);

    if (queue.length > 5) {
        // 寻找队列中最重要的节点（如 ERROR, 或者是最后的 Terminal）直接跃迁
        const criticalIndex = queue.findIndex(q => q.state === 'ERROR' || q.isTerminal);
        if (criticalIndex !== -1) {
            nextItem = queue[criticalIndex];
            remainingQueue = queue.slice(criticalIndex + 1);
        }
    }

    set({ 
        currentVisualState: nextItem, 
        queue: remainingQueue 
    });

    // 动态计算当前状态的驻留时间
    const currentQueueLength = remainingQueue.length;
    let actualDwellTime = MIN_DWELL_TIME;
    
    // 拥塞加速机制
    if (currentQueueLength >= WARP_SPEED_THRESHOLD) {
        actualDwellTime = WARP_DWELL_TIME;
    }

    // 如果是 Terminal 节点，通常驻留后清理状态
    if (nextItem.isTerminal) {
       setTimeout(() => {
           set({ currentVisualState: null }); // 触发离场动画
           get().processQueue();
       }, MIN_DWELL_TIME); // Terminal 节点固定驻留，不加速，让用户看清"已完成"
       return;
    }

    // 延时触发下一个
    setTimeout(() => {
      get()._popNext();
    }, actualDwellTime);
  }
}));
