import { create } from 'zustand';
import { ChatStatusPayload } from '../../shared/types';

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
  /**
   * 消费后端 EVT_CHAT_STATUS 事件。
   * 做什么：接收后端 ChatStatusPublisher 推送的状态通知，映射为前端 VisualStateItem 并入队。
   * 为什么这样做：状态文案由后端统一管理（_CHAT_STATUS_TEXTS），前端仅负责渲染。
   * 边界条件：is_visible=false 时不入队；is_terminal=true 表示该阶段生命周期结束。
   */
  onChatStatus: (payload: ChatStatusPayload) => void;
  /**
   * 清空当前状态并回到空闲态。
   */
  clearToIdle: () => void;
}

/** 后端 ChatStatusStage 到前端 colorTheme 的映射表。 */
const STAGE_TO_THEME: Record<string, 'blue' | 'purple' | 'red' | 'cyan'> = {
  input_reconstruction: 'purple',
  session_context_load: 'blue',
  rag_retrieval: 'cyan',
  knowledge_rag: 'blue',
  user_profile_injection: 'purple',
  context_governance: 'purple',
  chat_prompt_assembly: 'cyan',
  llm_streaming: 'cyan',
  response_persistence: 'cyan',
  finalize: 'cyan',
};

/** 后端 ChatStatusState 到前端 VisualStateItem.state 的映射。 */
function mapState(backendState: string): VisualStateItem['state'] {
  switch (backendState) {
    case 'running':
    case 'started':
      return 'RUNNING';
    case 'completed':
      return 'COMPLETED';
    case 'error':
    case 'cancelled':
      return 'ERROR';
    default:
      return 'COMPLETED';
  }
}

const MIN_DWELL_TIME = 800; // 核心防跳跃机制：强制驻留 800ms
const WARP_SPEED_THRESHOLD = 3; // 队列拥塞阈值
const WARP_DWELL_TIME = 200; // 曲率加速模式下的驻留时间

export const useVisualStatusQueue = create<VisualStatusQueueState>((set, get) => ({
  queue: [],
  currentVisualState: null,
  isProcessing: false,

  onChatStatus: (payload) => {
    // is_visible=false 时不展示（如跳过/静默通知）
    if (!payload.is_visible) {
      return;
    }

    const item: VisualStateItem = {
      id: `${payload.message_id}-${payload.stage}-${payload.sequence}`,
      stage: payload.stage,
      state: mapState(payload.state),
      text: payload.display_text || '',
      isTerminal: payload.is_terminal || false,
      colorTheme: STAGE_TO_THEME[payload.stage] || 'blue',
    };

    // 如果文本为空，且不是 terminal 节点，无需入队
    if (!item.text && !item.isTerminal) return;

    get().enqueue(item);
  },

  clearToIdle: () => {
    set({ queue: [], currentVisualState: null, isProcessing: false });
  },

  enqueue: (item) => {
    set((state) => ({ queue: [...state.queue, item] }));
    
    if (!get().isProcessing) {
      get().processQueue();
    }
  },

  processQueue: () => {
    const { queue, _popNext } = get();
    if (queue.length === 0) {
      set({ isProcessing: false });
      return;
    }

    set({ isProcessing: true });
    _popNext();
  },

  _popNext: () => {
    const { queue, currentVisualState } = get();
    
    // 队列已空时的处理
    if (queue.length === 0) {
      if (currentVisualState?.isTerminal) {
        // 当前显示的是一个 terminal 状态，且没有后续任务，彻底清空回到空闲态
        get().clearToIdle();
      } else {
        // 当前状态不是 terminal，可能后续还有更新，保留显示，标记非处理态
        set({ isProcessing: false });
      }
      return;
    }

    let nextItem = queue[0];
    let remainingQueue = queue.slice(1);

    // 状态修剪 (State Pruning): 如果积压极度严重，丢弃中间过渡态，直接跳到重要态
    if (queue.length > 5) {
      const criticalIndex = queue.findIndex(q => q.state === 'ERROR' || (q.isTerminal && !q.text));
      if (criticalIndex !== -1) {
        nextItem = queue[criticalIndex];
        remainingQueue = queue.slice(criticalIndex + 1);
      }
    }

    // 特殊情况：纯清理指令（空文案且是 terminal），无需任何驻留，直接清理当前显示
    if (nextItem.isTerminal && !nextItem.text) {
      set({ currentVisualState: null, queue: remainingQueue });
      get()._popNext(); // 递归处理下一项
      return;
    }

    // 更新当前视觉状态
    set({ currentVisualState: nextItem, queue: remainingQueue });

    // 动态计算驻留时间
    let actualDwellTime = MIN_DWELL_TIME;
    if (remainingQueue.length >= WARP_SPEED_THRESHOLD) {
      actualDwellTime = WARP_DWELL_TIME;
    }

    // 延时后继续调度队列
    setTimeout(() => {
      get()._popNext();
    }, actualDwellTime);
  }
}));
