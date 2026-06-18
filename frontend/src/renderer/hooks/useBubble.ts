/**
 * Luna AI 气泡渲染 Hook
 *
 * 重构说明（根据 core_issues_fix_plan.md）：
 * - 废弃：每收到一个数据块就立即渲染的逻辑
 * - 采用：通过缓冲队列（Queue）进行控制
 * - 限制：界面上最多同时渲染并展示三个气泡
 * - 计算：根据每个气泡内的实际字数，动态计算并分配成正比的屏幕停留时间
 * - 优化：基于生命周期的平滑等待机制，不再强制淘汰最老气泡
 * - 修复：气泡必须严格按照渲染顺序依次消失，确保消失顺序与出现顺序严格一致
 *
 * 本次重构目标：
 * - 不再依赖脆弱的“全部气泡完成后再猜测是否该提交近期记忆”
 * - 改为围绕“批次（batch）”建立确定性的生命周期状态机
 * - 每个回答批次都显式经历：收集中 → 等待沉降 → 可提交近期记忆 → 已提交
 * - 每个气泡都显式经历：队列中 → 显示中 → 等待消失 → 消失动画中 → 已移除
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import gsap from 'gsap';

const BUBBLE_EVENT_NAME = {
  SHOW: 'luna:show-bubble',
  STREAM_FINISHED: 'luna:bubble-stream-finished',
  BATCH_SETTLED: 'luna:bubble-batch-settled',
  RECENT_MEMORY_COMMITTED: 'luna:recent-memory-committed',
  ALL_COMPLETE: 'luna:all-bubbles-complete',
  BATCH_STAGE_CHANGED: 'luna:bubble-batch-stage-changed',
} as const;

const LEGACY_BUBBLE_BATCH_ID = '__legacy_bubble_batch__';
/** 最大可见气泡数。串行阻塞队列模式下固定为 1，确保一次只显示一个气泡。 */
const MAX_BUBBLES = 1;
const MIN_BUBBLE_GAP_MS = 800;
const BUBBLE_LEAVING_ANIMATION_MS = 300;

/** 每字符基础驻留时间（毫秒），用于按文本长度正比例计算 TTL。 */
const BASE_TTL_PER_CHAR = 100;
/** 最小驻留时间（毫秒），确保极短文本也有足够的阅读时间。 */
const MIN_TTL = 800;
/** 最大驻留时间（毫秒），保证最多 3 秒。 */
const MAX_TTL = 3000;
/** 兜底 TTL（文本为空时）。 */
const FALLBACK_TTL = 800;

type BubbleLifecycleStage =
  | 'visible'
  | 'awaiting-removal'
  | 'leaving';

type BubbleBatchStage =
  | 'collecting'
  | 'waiting-settle'
  | 'ready-to-commit'
  | 'committed';

export interface Bubble {
  id: number;
  batchId: string;
  text: string;
  leaving: boolean;
  /** 气泡在渲染队列中的序号，用于确保消失顺序 */
  renderIndex: number;
  /** 当前气泡生命周期阶段 */
  stage: BubbleLifecycleStage;
}

interface QueueItem {
  id: number;
  batchId: string;
  text: string;
  duration: number;
  renderIndex: number;
}

/** 待消失气泡的信息 */
interface PendingRemoval {
  id: number;
  batchId: string;
  renderIndex: number;
}

interface BubbleBatchRuntime {
  batchId: string;
  stage: BubbleBatchStage;
  totalCreated: number;
  queuedCount: number;
  visibleCount: number;
  awaitingRemovalCount: number;
  leavingCount: number;
  removedCount: number;
  finishedSignalReceived: boolean;
  settledEmitted: boolean;
  committed: boolean;
  lastUpdatedAt: number;
}

interface ShowBubbleEventDetail {
  text: string;
  duration?: number;
  batchId?: string;
}

interface BubbleStreamFinishedEventDetail {
  batchId: string;
  finishedAt?: number;
}

interface RecentMemoryCommittedEventDetail {
  batchId: string;
  msgId?: string;
  reason?: string;
}

interface BubbleBatchSettledEventDetail {
  batchId: string;
  reason: string;
  summary: BubbleBatchSnapshot;
}

interface BubbleBatchSnapshot {
  batchId: string;
  stage: BubbleBatchStage;
  totalCreated: number;
  queuedCount: number;
  visibleCount: number;
  awaitingRemovalCount: number;
  leavingCount: number;
  removedCount: number;
  finishedSignalReceived: boolean;
  settledEmitted: boolean;
  committed: boolean;
  activeBubbleCount: number;
  lastUpdatedAt: number;
}

export const useBubble = () => {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const bubblesRef = useRef<Bubble[]>([]);
  const bubbleElsRef = useRef<Map<number, HTMLDivElement>>(new Map());
  const bubbleIdCounter = useRef(0);
  const renderIndexCounter = useRef(0);

  // 缓冲队列和调度器状态
  const queueRef = useRef<QueueItem[]>([]);
  const isProcessingRef = useRef(false);

  // 阻塞等待队列，用于在气泡达到上限时挂起新的渲染任务
  const spaceAvailableResolversRef = useRef<(() => void)[]>([]);

  // 消失顺序控制相关状态
  // 待消失队列：存储所有 TTL 已到期但尚未执行消失的气泡（按 renderIndex 排序）
  const pendingRemovalQueueRef = useRef<PendingRemoval[]>([]);
  // 标记当前是否有气泡正在执行消失动画
  const removalInProgressRef = useRef(false);

  // 批次状态机：以 assistant 回复批次为单位聚合生命周期
  const batchRuntimeMapRef = useRef<Map<string, BubbleBatchRuntime>>(new Map());

  // 全局空闲态兼容标记，保留给现有链路做兜底观察
  const allCompleteDispatchedRef = useRef(true);

  /**
   * 统一更新全局空闲标记。
   * 做什么：向 window 暴露当前是否完全没有气泡工作在执行。
   * 为什么这样做：兼容既有链路中的全局空闲态读取，但不再作为近期记忆提交的唯一依据。
   * 输入输出：输入是否空闲；无返回值。
   * 边界条件：仅反映全局气泡系统是否空闲，不代表某个批次是否已可提交。
   * 异常行为：无。
   */
  const updateGlobalBubbleIdleFlag = useCallback((isIdle: boolean) => {
    (window as any).__LUNA_IS_BUBBLES_IDLE__ = isIdle;
  }, []);

  /**
   * 构建批次快照。
   * 做什么：把运行时批次状态压平成适合事件透出的调试快照。
   * 为什么这样做：近期记忆提交问题本质是生命周期问题，必须让状态可追踪。
   * 输入输出：输入批次运行时对象，输出只读快照。
   * 边界条件：activeBubbleCount 由各阶段计数实时聚合，避免外部推断。
   * 异常行为：无。
   */
  const buildBatchSnapshot = useCallback((batch: BubbleBatchRuntime): BubbleBatchSnapshot => {
    const activeBubbleCount =
      batch.queuedCount +
      batch.visibleCount +
      batch.awaitingRemovalCount +
      batch.leavingCount;

    return {
      batchId: batch.batchId,
      stage: batch.stage,
      totalCreated: batch.totalCreated,
      queuedCount: batch.queuedCount,
      visibleCount: batch.visibleCount,
      awaitingRemovalCount: batch.awaitingRemovalCount,
      leavingCount: batch.leavingCount,
      removedCount: batch.removedCount,
      finishedSignalReceived: batch.finishedSignalReceived,
      settledEmitted: batch.settledEmitted,
      committed: batch.committed,
      activeBubbleCount,
      lastUpdatedAt: batch.lastUpdatedAt,
    };
  }, []);

  /**
   * 获取或创建批次运行时对象。
   * 做什么：确保每个 batchId 都有独立的状态机记录。
   * 为什么这样做：近期记忆提交必须按“回答批次”而不是按全局气泡池判断。
   * 输入输出：输入 batchId，输出对应运行时对象。
   * 边界条件：相同 batchId 只会复用同一条记录。
   * 异常行为：无。
   */
  const ensureBatchRuntime = useCallback((batchId: string): BubbleBatchRuntime => {
    const existing = batchRuntimeMapRef.current.get(batchId);
    if (existing) {
      return existing;
    }

    const created: BubbleBatchRuntime = {
      batchId,
      stage: 'collecting',
      totalCreated: 0,
      queuedCount: 0,
      visibleCount: 0,
      awaitingRemovalCount: 0,
      leavingCount: 0,
      removedCount: 0,
      finishedSignalReceived: false,
      settledEmitted: false,
      committed: false,
      lastUpdatedAt: Date.now(),
    };

    batchRuntimeMapRef.current.set(batchId, created);
    return created;
  }, []);

  /**
   * 派发批次阶段变化事件。
   * 做什么：在批次阶段切换时对外广播快照。
   * 为什么这样做：便于调试“为什么该轮还不能提交近期记忆”。
   * 输入输出：输入批次对象与触发原因；输出为事件副作用。
   * 边界条件：仅在阶段实际发生变化时派发，避免噪音。
   * 异常行为：无。
   */
  const emitBatchStageChanged = useCallback((batch: BubbleBatchRuntime, reason: string) => {
    window.dispatchEvent(
      new CustomEvent(BUBBLE_EVENT_NAME.BATCH_STAGE_CHANGED, {
        detail: {
          batchId: batch.batchId,
          reason,
          summary: buildBatchSnapshot(batch),
        },
      })
    );
  }, [buildBatchSnapshot]);

  /**
   * 切换批次阶段。
   * 做什么：统一更新批次 stage，并记录更新时间。
   * 为什么这样做：避免在多个异步回调中散落修改 stage，导致状态漂移。
   * 输入输出：输入批次对象、目标阶段和原因；无返回值。
   * 边界条件：相同阶段不会重复派发事件。
   * 异常行为：无。
   */
  const setBatchStage = useCallback((batch: BubbleBatchRuntime, nextStage: BubbleBatchStage, reason: string) => {
    batch.lastUpdatedAt = Date.now();
    if (batch.stage === nextStage) {
      return;
    }
    batch.stage = nextStage;
    emitBatchStageChanged(batch, reason);
  }, [emitBatchStageChanged]);

  /**
   * 统一同步气泡列表。
   * 做什么：同时写入 ref 与 React state。
   * 为什么这样做：React state 更新是异步批处理；生命周期检查必须始终读取同一份最新数据。
   * 输入输出：输入新的气泡数组；无返回值。
   * 边界条件：ref 作为单一事实来源，state 仅用于渲染。
   * 异常行为：无。
   */
  const syncBubblesState = useCallback((nextBubbles: Bubble[]) => {
    bubblesRef.current = nextBubbles;
    setBubbles(nextBubbles);
  }, []);

  /**
   * 触发某个批次“已沉降，可提交近期记忆”的事件。
   * 做什么：当且仅当批次收到流结束信号，且该批次所有气泡都已完全移除时派发。
   * 为什么这样做：这是真正稳健的提交判定点，比“全局所有气泡都没了”更精确。
   * 输入输出：输入 batchId 与原因；输出为批次沉降事件。
   * 边界条件：同一批次只派发一次。
   * 异常行为：无。
   */
  const settleBatchIfReady = useCallback((batchId: string, reason: string) => {
    const batch = batchRuntimeMapRef.current.get(batchId);
    if (!batch) {
      return;
    }

    batch.lastUpdatedAt = Date.now();

    const activeBubbleCount =
      batch.queuedCount +
      batch.visibleCount +
      batch.awaitingRemovalCount +
      batch.leavingCount;

    if (!batch.finishedSignalReceived) {
      return;
    }

    if (activeBubbleCount > 0) {
      setBatchStage(batch, 'waiting-settle', reason);
      return;
    }

    if (batch.settledEmitted) {
      return;
    }

    batch.settledEmitted = true;
    setBatchStage(batch, 'ready-to-commit', reason);

    window.dispatchEvent(
      new CustomEvent<BubbleBatchSettledEventDetail>(BUBBLE_EVENT_NAME.BATCH_SETTLED, {
        detail: {
          batchId,
          reason,
          summary: buildBatchSnapshot(batch),
        },
      })
    );
  }, [buildBatchSnapshot, setBatchStage]);

  /**
   * 清理已终态的批次。
   * 做什么：在近期记忆确认提交后释放批次运行时记录。
   * 为什么这样做：避免长时间运行后批次状态无限累积。
   * 输入输出：输入 batchId；无返回值。
   * 边界条件：只有 committed 且没有任何活跃气泡时才删除。
   * 异常行为：无。
   */
  const cleanupBatchIfTerminal = useCallback((batchId: string) => {
    const batch = batchRuntimeMapRef.current.get(batchId);
    if (!batch) {
      return;
    }

    const activeBubbleCount =
      batch.queuedCount +
      batch.visibleCount +
      batch.awaitingRemovalCount +
      batch.leavingCount;

    if (batch.committed && activeBubbleCount === 0) {
      batchRuntimeMapRef.current.delete(batchId);
    }
  }, []);

  /**
   * 检查全局气泡系统是否空闲。
   * 做什么：仅作为兼容性的全局状态广播，不参与近期记忆提交的主判定。
   * 为什么这样做：提交判定现在按 batch 进行，但历史链路仍可能关心全局是否无气泡。
   * 输入输出：无输入；输出为空闲标记和兼容事件副作用。
   * 边界条件：全局事件仍然保持“一批工作只发一次”。
   * 异常行为：无。
   */
  const checkGlobalIdleState = useCallback(() => {
    const hasQueue = queueRef.current.length > 0;
    const hasBubbles = bubblesRef.current.length > 0;
    const hasPendingRemoval = pendingRemovalQueueRef.current.length > 0;
    const isProcessing = isProcessingRef.current;
    const isRemoving = removalInProgressRef.current;

    const isIdle = !hasQueue && !hasBubbles && !hasPendingRemoval && !isProcessing && !isRemoving;
    updateGlobalBubbleIdleFlag(isIdle);

    if (isIdle) {
      if (!allCompleteDispatchedRef.current) {
        allCompleteDispatchedRef.current = true;
        window.dispatchEvent(new CustomEvent(BUBBLE_EVENT_NAME.ALL_COMPLETE));
      }
      return;
    }

    allCompleteDispatchedRef.current = false;
  }, [updateGlobalBubbleIdleFlag]);

  /**
   * 下一帧执行一次全局空闲态检查。
   * 做什么：等待 React 提交 DOM 后再检查是否完全空闲。
   * 为什么这样做：某些阶段切换只影响 CSS class 或 DOM 位置，需要等待浏览器完成一次提交。
   * 输入输出：无。
   * 边界条件：仅做全局兼容态检查，不影响批次沉降主逻辑。
   * 异常行为：无。
   */
  const requestGlobalIdleCheck = useCallback(() => {
    requestAnimationFrame(() => {
      checkGlobalIdleState();
    });
  }, [checkGlobalIdleState]);

  useEffect(() => {
    updateGlobalBubbleIdleFlag(true);
    return () => {
      updateGlobalBubbleIdleFlag(true);
    };
  }, [updateGlobalBubbleIdleFlag]);

  useEffect(() => {
    /**
     * 处理“流式输出结束”信号。
     * 做什么：把某个 batch 标记为“不会再有新气泡进入”。
     * 为什么这样做：近期记忆提交必须同时满足“流已结束”与“气泡已沉降”。
     * 输入输出：输入 batchId；输出为批次状态切换。
     * 边界条件：如果结束信号到来时该批次已经没有任何活跃气泡，则立即进入可提交状态。
     * 异常行为：无。
     */
    const handleStreamFinished = (event: Event) => {
      const customEvent = event as CustomEvent<BubbleStreamFinishedEventDetail>;
      const batchId = customEvent.detail?.batchId;
      if (!batchId) {
        return;
      }

      const batch = ensureBatchRuntime(batchId);
      batch.finishedSignalReceived = true;
      batch.lastUpdatedAt = Date.now();

      settleBatchIfReady(batchId, 'stream-finished');
      checkGlobalIdleState();
    };

    /**
     * 处理“近期记忆已提交”确认信号。
     * 做什么：把批次从 ready-to-commit 推进到 committed，并尝试清理运行时状态。
     * 为什么这样做：只有外部真正写入 recentQA 成功后，该批次生命周期才算闭环。
     * 输入输出：输入 batchId；输出为批次终态切换。
     * 边界条件：如果批次已被提前清理，则安全忽略。
     * 异常行为：无。
     */
    const handleRecentMemoryCommitted = (event: Event) => {
      const customEvent = event as CustomEvent<RecentMemoryCommittedEventDetail>;
      const batchId = customEvent.detail?.batchId;
      if (!batchId) {
        return;
      }

      const batch = batchRuntimeMapRef.current.get(batchId);
      if (!batch) {
        return;
      }

      batch.committed = true;
      batch.lastUpdatedAt = Date.now();
      setBatchStage(batch, 'committed', customEvent.detail?.reason ?? 'recent-memory-committed');
      cleanupBatchIfTerminal(batchId);
      checkGlobalIdleState();
    };

    window.addEventListener(BUBBLE_EVENT_NAME.STREAM_FINISHED, handleStreamFinished);
    window.addEventListener(BUBBLE_EVENT_NAME.RECENT_MEMORY_COMMITTED, handleRecentMemoryCommitted);

    return () => {
      window.removeEventListener(BUBBLE_EVENT_NAME.STREAM_FINISHED, handleStreamFinished);
      window.removeEventListener(BUBBLE_EVENT_NAME.RECENT_MEMORY_COMMITTED, handleRecentMemoryCommitted);
    };
  }, [checkGlobalIdleState, cleanupBatchIfTerminal, ensureBatchRuntime, settleBatchIfReady, setBatchStage]);

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  /**
   * 触发等待队列继续执行。
   * 做什么：当有气泡被真正移除后，唤醒因屏幕容量限制而阻塞的渲染任务。
   * 为什么这样做：保证最大气泡数量限制下的串行推进。
   * 输入输出：无。
   * 边界条件：没有等待者时直接返回。
   * 异常行为：无。
   */
  const notifySpaceAvailable = useCallback(() => {
    const resolve = spaceAvailableResolversRef.current.shift();
    resolve?.();
  }, []);

  /**
   * 把可见气泡推进到“等待消失”阶段。
   * 做什么：TTL 到期后不立即删除，而是先进入等待消失队列。
   * 为什么这样做：需要保证多个气泡严格按 renderIndex 先后退场。
   * 输入输出：输入气泡 id、batchId、renderIndex；输出为阶段迁移副作用。
   * 边界条件：只有当前仍处于 visible 阶段的气泡才会被推进。
   * 异常行为：无。
   */
  const scheduleRemoval = useCallback((id: number, batchId: string, renderIndex: number) => {
    const batch = batchRuntimeMapRef.current.get(batchId);
    const targetBubble = bubblesRef.current.find((bubble) => bubble.id === id);

    if (!batch || !targetBubble || targetBubble.stage !== 'visible') {
      return;
    }

    batch.visibleCount = Math.max(0, batch.visibleCount - 1);
    batch.awaitingRemovalCount += 1;
    batch.lastUpdatedAt = Date.now();

    const nextBubbles = bubblesRef.current.map((bubble) =>
      bubble.id === id
        ? { ...bubble, stage: 'awaiting-removal' as const }
        : bubble
    );
    syncBubblesState(nextBubbles);

    pendingRemovalQueueRef.current.push({ id, batchId, renderIndex });
    settleBatchIfReady(batchId, 'bubble-waiting-removal');
    requestGlobalIdleCheck();
  }, [requestGlobalIdleCheck, settleBatchIfReady, syncBubblesState]);

  /**
   * 处理待消失队列。
   * 做什么：让最早渲染的气泡优先进入离场动画，直到完全移除。
   * 为什么这样做：保持视觉顺序与语义顺序一致，避免后出现的气泡先消失。
   * 输入输出：无输入；输出为气泡阶段流转副作用。
   * 边界条件：同一时刻只允许一个气泡执行离场动画。
   * 异常行为：无。
   */
  const processRemovalQueue = useCallback(function processRemovalQueueImpl() {
    if (removalInProgressRef.current) {
      return;
    }

    pendingRemovalQueueRef.current.sort((a, b) => a.renderIndex - b.renderIndex);

    if (pendingRemovalQueueRef.current.length === 0) {
      requestGlobalIdleCheck();
      return;
    }

    const nextRemoval = pendingRemovalQueueRef.current[0];
    const onScreenBubbles = bubblesRef.current.filter((bubble) => bubble.stage !== 'leaving');

    if (onScreenBubbles.length === 0) {
      requestGlobalIdleCheck();
      return;
    }

    const minRenderIndex = Math.min(...onScreenBubbles.map((bubble) => bubble.renderIndex));
    if (nextRemoval.renderIndex !== minRenderIndex) {
      return;
    }

    pendingRemovalQueueRef.current.shift();
    removalInProgressRef.current = true;

    const batch = batchRuntimeMapRef.current.get(nextRemoval.batchId);
    const targetBubble = bubblesRef.current.find((bubble) => bubble.id === nextRemoval.id);

    if (!batch || !targetBubble) {
      removalInProgressRef.current = false;
      settleBatchIfReady(nextRemoval.batchId, 'bubble-missing-before-leaving');
      processRemovalQueueImpl();
      requestGlobalIdleCheck();
      return;
    }

    if (targetBubble.stage === 'awaiting-removal') {
      batch.awaitingRemovalCount = Math.max(0, batch.awaitingRemovalCount - 1);
      batch.leavingCount += 1;
      batch.lastUpdatedAt = Date.now();
    }

    const leavingBubbles = bubblesRef.current.map((bubble) =>
      bubble.id === nextRemoval.id
        ? { ...bubble, leaving: true, stage: 'leaving' as const }
        : bubble
    );
    syncBubblesState(leavingBubbles);

    setTimeout(() => {
      const runtime = batchRuntimeMapRef.current.get(nextRemoval.batchId);
      if (runtime) {
        runtime.leavingCount = Math.max(0, runtime.leavingCount - 1);
        runtime.removedCount += 1;
        runtime.lastUpdatedAt = Date.now();
      }

      const nextBubbles = bubblesRef.current.filter((bubble) => bubble.id !== nextRemoval.id);
      syncBubblesState(nextBubbles);
      bubbleElsRef.current.delete(nextRemoval.id);

      removalInProgressRef.current = false;
      notifySpaceAvailable();
      settleBatchIfReady(nextRemoval.batchId, 'bubble-removed');
      processRemovalQueueImpl();
      checkGlobalIdleState();
      cleanupBatchIfTerminal(nextRemoval.batchId);
    }, BUBBLE_LEAVING_ANIMATION_MS);
  }, [checkGlobalIdleState, cleanupBatchIfTerminal, notifySpaceAvailable, requestGlobalIdleCheck, settleBatchIfReady, syncBubblesState]);

  /**
   * 异步气泡调度器。
   * 做什么：按先后顺序逐个把队列项推进到屏幕上。
   * 为什么这样做：需要同时控制最大可见数量、最小弹出间隔和位移动画。
   * 输入输出：无。
   * 边界条件：调度器是单实例串行运行，避免并发消费同一队列。
   * 异常行为：异常时通过 finally 回收 processing 标记，避免队列永久卡死。
   */
  const processQueue = useCallback(async () => {
    if (isProcessingRef.current) {
      return;
    }

    isProcessingRef.current = true;
    updateGlobalBubbleIdleFlag(false);

    try {
      while (queueRef.current.length > 0) {
        const activeBubbles = bubblesRef.current.length;
        if (activeBubbles >= MAX_BUBBLES) {
          await new Promise<void>((resolve) => {
            spaceAvailableResolversRef.current.push(resolve);
          });
          continue;
        }

        const item = queueRef.current.shift();
        if (!item) {
          continue;
        }

        const batch = ensureBatchRuntime(item.batchId);
        batch.queuedCount = Math.max(0, batch.queuedCount - 1);
        batch.visibleCount += 1;
        batch.lastUpdatedAt = Date.now();

        const prevPositions = new Map<number, number>();
        bubbleElsRef.current.forEach((el, key) => {
          try {
            prevPositions.set(key, el.getBoundingClientRect().top);
          } catch {
            // DOM 已卸载时忽略，避免打断主链路
          }
        });

        syncBubblesState([
          ...bubblesRef.current,
          {
            id: item.id,
            batchId: item.batchId,
            text: item.text,
            leaving: false,
            renderIndex: item.renderIndex,
            stage: 'visible',
          },
        ]);

        requestAnimationFrame(() => {
          bubbleElsRef.current.forEach((el, key) => {
            if (prevPositions.has(key) && key !== item.id) {
              const prevTop = prevPositions.get(key)!;
              const currentTop = el.getBoundingClientRect().top;
              const dy = prevTop - currentTop;
              if (Math.abs(dy) > 0.5) {
                gsap.fromTo(el, { y: dy }, { y: 0, duration: 0.3, ease: 'power2.out' });
              }
            }
          });
        });

        setTimeout(() => {
          scheduleRemoval(item.id, item.batchId, item.renderIndex);
          // 使用事件派发来解决 Hook 循环依赖，确保能够触发 processRemovalQueue
          window.dispatchEvent(new CustomEvent('luna:internal:trigger-removal'));
        }, item.duration);

        await new Promise((resolve) => setTimeout(resolve, MIN_BUBBLE_GAP_MS));
      }
    } finally {
      isProcessingRef.current = false;
      requestGlobalIdleCheck();
    }
  }, [ensureBatchRuntime, requestGlobalIdleCheck, scheduleRemoval, syncBubblesState, updateGlobalBubbleIdleFlag]);

  // 挂载内部事件监听器，打通从 processQueue -> scheduleRemoval -> processRemovalQueue 的通路
  useEffect(() => {
    const handleTriggerRemoval = () => {
      processRemovalQueue();
    };
    window.addEventListener('luna:internal:trigger-removal', handleTriggerRemoval as EventListener);
    return () => {
      window.removeEventListener('luna:internal:trigger-removal', handleTriggerRemoval as EventListener);
    };
  }, [processRemovalQueue]);

  /**
   * 显示气泡。
   * 做什么：创建一个属于指定 batch 的气泡并推进队列。
   * 为什么这样做：回答批次和气泡生命周期必须一一对应，近期记忆才能精确提交。
   * 输入输出：输入文本、时长和批次 ID；无返回值。
   * 边界条件：未提供 batchId 时会落入 legacy 批次，仅用于兼容旧链路，不参与近期记忆提交。
   * 异常行为：空文本会被上层过滤，不在此重复兜底。
   */
  const showBubble = useCallback((text: string, duration?: number, batchId?: string) => {
    const normalizedBatchId = batchId?.trim() || LEGACY_BUBBLE_BATCH_ID;
    const id = bubbleIdCounter.current++;
    const renderIndex = renderIndexCounter.current++;
    /**
     * 动态 TTL 计算：严格按文本长度正比例，夹紧 [MIN_TTL, MAX_TTL]。
     * 公式：clamp(text.length × BASE_TTL_PER_CHAR, MIN_TTL, MAX_TTL)
     * 每字符 100ms：8 字 → 800ms，20 字 → 2000ms，30 字及以上 → 3000ms（上限）
     * 外部传入 duration 仍可覆盖，但受 MAX_TTL 上限约束。
     */
    const calcDuration = duration !== undefined
      ? Math.min(duration, MAX_TTL)
      : text.length > 0
        ? Math.min(Math.max(text.length * BASE_TTL_PER_CHAR, MIN_TTL), MAX_TTL)
        : FALLBACK_TTL;

    const batch = ensureBatchRuntime(normalizedBatchId);
    batch.totalCreated += 1;
    batch.queuedCount += 1;
    batch.lastUpdatedAt = Date.now();

    // 新气泡进入时，代表全局工作重新开始
    allCompleteDispatchedRef.current = false;
    updateGlobalBubbleIdleFlag(false);

    queueRef.current.push({
      id,
      batchId: normalizedBatchId,
      text,
      duration: calcDuration,
      renderIndex,
    });

    if (!batch.finishedSignalReceived) {
      setBatchStage(batch, 'collecting', 'bubble-enqueued');
    }

    processQueue();
  }, [ensureBatchRuntime, processQueue, setBatchStage, updateGlobalBubbleIdleFlag]);

  useEffect(() => {
    const handleShowBubble = (event: Event) => {
      const customEvent = event as CustomEvent<ShowBubbleEventDetail>;
      const { text, duration, batchId } = customEvent.detail ?? {};
      if (!text || !text.trim()) {
        return;
      }
      showBubble(text, duration, batchId);
    };

    window.addEventListener(BUBBLE_EVENT_NAME.SHOW, handleShowBubble);
    return () => {
      window.removeEventListener(BUBBLE_EVENT_NAME.SHOW, handleShowBubble);
    };
  }, [showBubble]);

  return { bubbles, showBubble, registerBubble };
};
