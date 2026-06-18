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
  /** 丢弃当前气泡并调度下一个（内部消费队列头项）。 */
  _popNext: () => void;
  /**
   * 消费后端 EVT_CHAT_STATUS 事件。
   * 做什么：接收后端 ChatStatusPublisher 推送的状态通知，映射为前端 VisualStateItem 并入队。
   * 为什么这样做：状态文案由后端统一管理（_CHAT_STATUS_TEXTS），前端仅负责渲染。
   * 边界条件：is_visible=false 时通常不入队；但如果 is_terminal=true 说明是清理指令，必须放行入队。
   */
  onChatStatus: (payload: ChatStatusPayload) => void;
  /**
   * 清空当前状态并回到空闲态。
   */
  clearToIdle: () => void;
  /**
   * 是否处于纯空闲态（无队列、无活跃状态、无连接问题）。
   */
  readonly isIdle: boolean;
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

// ============================================================
// 动态 TTL 计算常量
// ============================================================

/** 每字符基础驻留时间（毫秒），用于按文本长度正比例计算 TTL。 */
const BASE_TTL_PER_CHAR = 100;

/** 最小驻留时间（毫秒），确保极短文本也有足够的阅读时间。 */
const MIN_TTL = 800;

/** 最大驻留时间（毫秒），防止长文本无限驻留，确保最多 3 秒。 */
const MAX_TTL = 3000;

/** 默认兜底 TTL（文本为空时）。 */
const FALLBACK_TTL = 800;

/** 离场动画持续时间（毫秒），等待 AnimatePresence 退出动画结束后再调度下一个。 */
const LEAVING_ANIMATION_MS = 400;

/**
 * 动态计算气泡驻留时间（TTL）。
 *
 * 做什么：严格按文本长度成比例计算存活时长。
 * 为什么这样做：短状态只需一瞥认识，长消息需要完整阅读时间。
 * 公式：clamp(text.length × BASE_TTL_PER_CHAR, MIN_TTL, MAX_TTL)
 *       每字符 100ms：10 字 → 1000ms，20 字 → 2000ms，30 字及以上 → 3000ms（上限）
 * 边界条件：空文本返回 FALLBACK_TTL 兜底。
 */
function calculateTTL(text: string): number {
  if (!text || text.length === 0) return FALLBACK_TTL;
  return Math.min(Math.max(text.length * BASE_TTL_PER_CHAR, MIN_TTL), MAX_TTL);
}

export const useVisualStatusQueue = create<VisualStatusQueueState>((set, get) => ({
  queue: [],
  currentVisualState: null,
  isProcessing: false,

  get isIdle(): boolean {
    return !get().currentVisualState && get().queue.length === 0 && !get().isProcessing;
  },

  onChatStatus: (payload) => {
    // is_visible=false 时通常不展示（如跳过/静默通知）
    // 但如果携带了 is_terminal=true，说明是后端 FinalizeNode 发出的清理指令，
    // 必须放行入队，否则状态栏永远不会回到空闲态。
    // finalize 节点: is_visible=false, is_terminal=true, display_text=""
    if (!payload.is_visible && !payload.is_terminal) {
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
    
    // ===== 队列已空时的处理 =====
    // 仅当当前状态是纯清理指令（terminal + 无文案）时才彻底清空
    // 为什么：中间节点的 COMPLETED 状态（如 "Luna想起来了~"）也会带 isTerminal=true，
    //       但带有文案，应保留显示而不是清空，等待下游节点的新状态入队。
    if (queue.length === 0) {
      if (currentVisualState?.isTerminal && !currentVisualState.text) {
        // 当前显示的是一个纯清理 terminal（来自 FinalizeNode），彻底清空回到空闲态
        get().clearToIdle();
      } else {
        // 当前状态不是纯清理 terminal，保留显示，标记非处理态
        set({ isProcessing: false });
      }
      return;
    }

    const nextItem = queue[0];
    const remainingQueue = queue.slice(1);

    // ===== 纯清理指令（空文案且是 terminal），无需任何驻留，直接清理并递归 =====
    if (nextItem.isTerminal && !nextItem.text) {
      set({ currentVisualState: null, queue: remainingQueue });
      get()._popNext(); // 递归处理下一项
      return;
    }

    // ===== 正常气泡渲染：更新状态 → TTL 驻留 → 离场动画 → 调度下一个 =====
    set({ currentVisualState: nextItem, queue: remainingQueue });

    // 动态计算驻留时间（严格按文本长度正比例，最多 3 秒）
    const actualDwellTime = calculateTTL(nextItem.text);

    // 第一阶段：TTL 自然耗尽
    setTimeout(() => {
      // 清除当前气泡，触发 AnimatePresence 离场动画
      // 为什么：先清除状态让前端 React 组件执行 exit 动画，然后再调度下一个，
      //        确保新旧气泡不会发生重叠或覆盖。
      set({ currentVisualState: null });

      // 第二阶段：等待离场动画完成后，再提取下一个队列项
      setTimeout(() => {
        // 直接调用 processQueue 重新检查队列
        // 为什么：不直接在 clear 中调用 _popNext，而是经过 processQueue，
        //        让 processQueue 统一处理 isProcessing 标记的切换。
        get().processQueue();
      }, LEAVING_ANIMATION_MS);
    }, actualDwellTime);
  }
}));
