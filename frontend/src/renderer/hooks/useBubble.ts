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
 * Phase 5 增强：当所有气泡渲染并消失完成后，触发 luna:all-bubbles-complete 事件
 * 用于通知外部模块（如 sseManager）可以安全地插入近期记忆，防止内容被截断
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import gsap from 'gsap';

export interface Bubble {
  id: number;
  text: string;
  leaving: boolean;
  /** 气泡在渲染队列中的序号，用于确保消失顺序 */
  renderIndex: number;
}

interface QueueItem {
  id: number;
  text: string;
  duration: number;
  renderIndex: number;
}

/** 待消失气泡的信息 */
interface PendingRemoval {
  id: number;
  renderIndex: number;
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
  const MAX_BUBBLES = 3;

  // 消失顺序控制相关状态
  // 待消失队列：存储所有 TTL 已到期但尚未执行消失的气泡（按 renderIndex 排序）
  const pendingRemovalQueueRef = useRef<PendingRemoval[]>([]);
  // 标记当前是否有气泡正在执行消失动画
  const removalInProgressRef = useRef(false);

  // Phase 5: 标记所有气泡是否已完成渲染和消失
  const hasPendingWorkRef = useRef(false);
  // 标记当前批次是否已触发过 luna:all-bubbles-complete 事件
  // 防止重复触发导致 [`addRecentQA()`](frontend/src/renderer/stores/sessionStore.ts:233) 重复追加
  const completedRef = useRef(true);

  /**
   * Phase 5: 检查是否有未完成的渲染/消失工作
   * 当所有工作完成时，触发 luna:all-bubbles-complete 事件
   * 注意：每个气泡批次只触发一次，触发后将 completedRef 置为 true，
   * 直至新的气泡任务到来（showBubble 调用时重置该标记）。
   */
  const updateBubbleIdleFlag = useCallback((isIdle: boolean) => {
    (window as any).__LUNA_IS_BUBBLES_IDLE__ = isIdle;
  }, []);

  const checkAllWorkDone = useCallback(() => {
    const hasQueue = queueRef.current.length > 0;
    const hasBubbles = bubblesRef.current.length > 0;
    const hasPendingRemoval = pendingRemovalQueueRef.current.length > 0;
    const isProcessing = isProcessingRef.current;
    const isRemoving = removalInProgressRef.current;

    const isIdle = !hasQueue && !hasBubbles && !hasPendingRemoval && !isProcessing && !isRemoving;
    updateBubbleIdleFlag(isIdle);

    // 如果已经触发完成事件，不再重复触发
    if (completedRef.current) {
      return;
    }

    // 如果没有气泡、没有队列、没有待消失、没有在处理中 → 全部完成
    if (isIdle) {
      completedRef.current = true;
      // 触发全局事件，通知外部（如 sseManager）可以安全插入近期记忆
      window.dispatchEvent(new CustomEvent('luna:all-bubbles-complete'));
      
      // Also release input lock just in case backend missed `is_finished` event
      import('../stores/sessionStore').then(({ useSessionStore }) => {
        useSessionStore.getState().clearAllWaitingStates();
      }).catch(console.error);
    }
  }, [updateBubbleIdleFlag]);

  /**
   * 立即请求一次完成态检查。
   * 做什么：在关键状态变更后下一帧执行 [`checkAllWorkDone()`](frontend/src/renderer/hooks/useBubble.ts:79)。
   * 为什么这样做：替代 500ms 轮询，确保最后一个气泡消失后能立刻触发完成事件。
   * 输入输出：无。
   * 边界条件：依赖 `requestAnimationFrame` 等待 React 提交最新 DOM 与状态。
   * 异常行为：无。
   */
  const requestCompletionCheck = useCallback(() => {
    requestAnimationFrame(() => {
      checkAllWorkDone();
    });
  }, [checkAllWorkDone]);

  useEffect(() => {
    updateBubbleIdleFlag(true);
    return () => {
      updateBubbleIdleFlag(true);
    };
  }, [updateBubbleIdleFlag]);

  // 同步最新状态到 ref，方便在异步循环中读取最新气泡数量
  useEffect(() => {
    bubblesRef.current = bubbles;
  }, [bubbles]);

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  /**
   * 触发等待队列继续执行
   * 当有气泡自然消亡后，调用此函数唤醒被阻塞的渲染任务
   */
  const notifySpaceAvailable = useCallback(() => {
    if (spaceAvailableResolversRef.current.length > 0) {
      const resolve = spaceAvailableResolversRef.current.shift();
      resolve?.();
    }
  }, []);

  /**
   * 处理待消失队列
   * 确保气泡按照渲染顺序依次消失：
   * - 只有队列中 renderIndex 最小（最早渲染）的气泡才能执行消失
   * - 消失完成后，继续检查队列中下一个气泡是否可以消失
   */
  const processRemovalQueue = useCallback(() => {
    // 如果当前有气泡正在执行消失动画，则不处理
    if (removalInProgressRef.current) {
      return;
    }

    // 按 renderIndex 排序，确保最早渲染的气泡排在队列头部
    pendingRemovalQueueRef.current.sort((a, b) => a.renderIndex - b.renderIndex);

    // 检查队列头部气泡是否可以消失
    if (pendingRemovalQueueRef.current.length === 0) {
      return;
    }

    const nextRemoval = pendingRemovalQueueRef.current[0];
    
    // 检查该气泡是否是当前所有活跃气泡中 renderIndex 最小的
    // 即：只有最早渲染的气泡才能先消失
    const activeBubbles = bubblesRef.current.filter(b => !b.leaving);
    const minRenderIndex = Math.min(...activeBubbles.map(b => b.renderIndex));
    
    if (nextRemoval.renderIndex !== minRenderIndex) {
      // 队列头部的气泡不是最早渲染的，需要等待更早的气泡先消失
      return;
    }

    // 标记正在执行消失动画
    removalInProgressRef.current = true;

    // 从待消失队列中移除
    pendingRemovalQueueRef.current.shift();

    // 执行消失逻辑
    setBubbles(prev => {
      const target = prev.find(b => b.id === nextRemoval.id);
      if (target && !target.leaving) {
        // 消失动画结束后（300ms），真正移除 DOM
        setTimeout(() => {
          setBubbles(current => {
            const nextBubbles = current.filter(b => b.id !== nextRemoval.id);
            bubblesRef.current = nextBubbles;
            return nextBubbles;
          });
          bubbleElsRef.current.delete(nextRemoval.id);
          
          // 消失动画完成，标记为可处理下一个
          removalInProgressRef.current = false;
          
          // 唤醒可能在等待的下一个气泡渲染
          notifySpaceAvailable();
          
          // 继续处理待消失队列中的下一个气泡
          processRemovalQueue();
          requestCompletionCheck();
        }, 300);
        
        const nextBubbles = prev.map(b => b.id === nextRemoval.id ? { ...b, leaving: true } : b);
        bubblesRef.current = nextBubbles;
        return nextBubbles;
      }
      return prev;
    });
  }, [notifySpaceAvailable, processRemovalQueue, requestCompletionCheck]);

  /**
   * 将气泡加入待消失队列
   * 当气泡 TTL 到期时调用，不立即执行消失，而是等待队列处理
   */
  const scheduleRemoval = useCallback((id: number, renderIndex: number) => {
    // 加入待消失队列
    pendingRemovalQueueRef.current.push({ id, renderIndex });
    
    // 尝试处理队列
    processRemovalQueue();
  }, [processRemovalQueue]);

  /**
   * 异步气泡调度器
   * 逐个按序渲染气泡，控制弹出间隔，并处理阻塞等待逻辑
   * 当活跃气泡达到最大数量时，暂停处理队列，等待有气泡自然消亡后继续
   */
  const processQueue = useCallback(async () => {
    // 如果正在处理中，则直接返回，避免并发冲突
    if (isProcessingRef.current) {
      return;
    }
    isProcessingRef.current = true;
    hasPendingWorkRef.current = true;

    while (queueRef.current.length > 0) {
      // 1. 检查当前活跃气泡数量（未处于 leaving 状态的）
      const activeBubbles = bubblesRef.current.filter(b => !b.leaving);
      
      // 如果达到最大限制，则阻塞当前循环，等待有气泡被移除后唤醒
      if (activeBubbles.length >= MAX_BUBBLES) {
        await new Promise<void>(resolve => {
          spaceAvailableResolversRef.current.push(resolve);
        });
        // 被唤醒后，重新进行 while 循环的条件检查，确保确实有空间
        continue;
      }

      const item = queueRef.current.shift()!;
      const { id, text, duration, renderIndex } = item;

      // 2. 记录旧位置 (用于 GSAP 平滑上移动画)
      const prevPositions = new Map<number, number>();
      bubbleElsRef.current.forEach((el, key) => {
        try { prevPositions.set(key, el.getBoundingClientRect().top); } catch (e) { /* ignore */ }
      });

      // 3. 添加新气泡（不再执行强制淘汰逻辑）
      setBubbles(prev => {
        const nextBubbles = [...prev, { id, text, leaving: false, renderIndex }];
        bubblesRef.current = nextBubbles;
        return nextBubbles;
      });

      // 4. 等待 DOM 更新后执行动画
      requestAnimationFrame(() => {
        bubbleElsRef.current.forEach((el, key) => {
          if (prevPositions.has(key) && key !== id) {
            const prevTop = prevPositions.get(key)!;
            const currentTop = el.getBoundingClientRect().top;
            const dy = prevTop - currentTop;
            if (Math.abs(dy) > 0.5) {
              gsap.fromTo(el, { y: dy }, { y: 0, duration: 0.3, ease: "power2.out" });
            }
          }
        });
      });

      // 5. 设置当前气泡的自然生命周期 (TTL)
      // TTL 结束后将气泡加入待消失队列，而不是立即执行消失
      setTimeout(() => {
        scheduleRemoval(id, renderIndex);
      }, duration);

      // 6. 强制等待一个最小弹出间隔，防止气泡一次性全部弹出
      await new Promise(resolve => setTimeout(resolve, 800));
    }

    isProcessingRef.current = false;
    hasPendingWorkRef.current = false;
    requestCompletionCheck();
  }, [requestCompletionCheck, scheduleRemoval]);

  /**
   * 显示气泡
   * @param text 气泡文本内容
   * @param duration 可选的自定义存活时间（毫秒）
   */
  const showBubble = useCallback((text: string, duration?: number) => {
    const id = bubbleIdCounter.current++;
    const renderIndex = renderIndexCounter.current++;
    
    // 新气泡任务开始时，重置完成标记并立刻更新全局空闲态。
    completedRef.current = false;
    updateBubbleIdleFlag(false);

    // 动态 TTL 计算策略：
    // 基础存活时间 2000ms，每个字符增加 250ms 的阅读时间。
    // 确保文本越长，气泡展示的时间越久，严格成正比。
    const calcDuration = duration ?? Math.max(2000, text.length * 250);
    
    queueRef.current.push({ id, text, duration: calcDuration, renderIndex });
    processQueue();
  }, [processQueue, updateBubbleIdleFlag]);

  return { bubbles, showBubble, registerBubble };
};
