/**
 * Luna AI 气泡渲染 Hook
 *
 * 重构说明（根据 core_issues_fix_plan.md）：
 * - 废弃：每收到一个数据块就立即渲染的逻辑
 * - 采用：通过缓冲队列（Queue）进行控制
 * - 限制：界面上最多同时渲染并展示三个气泡
 * - 计算：根据每个气泡内的实际字数，动态计算并分配成正比的屏幕停留时间
 */
import { useState, useRef, useCallback } from 'react';
import gsap from 'gsap';

export interface Bubble {
  id: number;
  text: string;
  leaving: boolean;
}

interface QueueItem {
  id: number;
  text: string;
  duration: number;
}

export const useBubble = () => {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const bubbleElsRef = useRef<Map<number, HTMLDivElement>>(new Map());
  const bubbleIdCounter = useRef(0);

  // 缓冲队列和调度器状态
  const queueRef = useRef<QueueItem[]>([]);
  const isProcessingRef = useRef(false);
  const MAX_BUBBLES = 3;

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  /**
   * 异步气泡调度器
   * 逐个按序渲染气泡，控制弹出间隔，并处理淘汰逻辑
   */
  const processQueue = useCallback(async () => {
    // 如果正在处理中，或队列为空，则直接返回
    if (isProcessingRef.current || queueRef.current.length === 0) {
      return;
    }
    isProcessingRef.current = true;

    while (queueRef.current.length > 0) {
      const item = queueRef.current.shift()!;
      const { id, text, duration } = item;

      // 1. 记录旧位置 (用于 GSAP 平滑上移动画)
      const prevPositions = new Map<number, number>();
      bubbleElsRef.current.forEach((el, key) => {
        try { prevPositions.set(key, el.getBoundingClientRect().top); } catch (e) { /* ignore */ }
      });

      // 2. 添加新气泡，并执行自动淘汰逻辑
      setBubbles(prev => {
        const next = [...prev, { id, text, leaving: false }];
        // 查找当前活跃（未 leaving）的气泡
        const activeBubbles = next.filter(b => !b.leaving);
        
        // 如果超过最大限制，强制淘汰最旧的
        if (activeBubbles.length > MAX_BUBBLES) {
          const oldest = activeBubbles[0];
          const oldestIndex = next.findIndex(b => b.id === oldest.id);
          if (oldestIndex !== -1) {
            next[oldestIndex] = { ...next[oldestIndex], leaving: true };
            // 触发 DOM 清理
            setTimeout(() => {
              setBubbles(current => current.filter(b => b.id !== oldest.id));
              bubbleElsRef.current.delete(oldest.id);
            }, 300);
          }
        }
        return next;
      });

      // 3. 等待 DOM 更新后执行动画
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

      // 4. 设置当前气泡的自然生命周期 (基于字数成正比计算的时长)
      setTimeout(() => {
        setBubbles(prev => {
          const target = prev.find(b => b.id === id);
          // 如果气泡还在且未被提前淘汰，则标记为 leaving
          if (target && !target.leaving) {
            setTimeout(() => {
              setBubbles(current => current.filter(b => b.id !== id));
              bubbleElsRef.current.delete(id);
            }, 300);
            return prev.map(b => b.id === id ? { ...b, leaving: true } : b);
          }
          return prev;
        });
      }, duration);

      // 5. 强制等待一个最小弹出间隔，防止气泡一次性全部弹出
      // 800ms 保证了视觉上的逐个弹出，同时允许气泡在屏幕上共存（因为 duration 通常远大于 800ms）
      await new Promise(resolve => setTimeout(resolve, 800));
    }

    isProcessingRef.current = false;
  }, []);

  const showBubble = useCallback((text: string, duration?: number) => {
    const id = bubbleIdCounter.current++;
    // 动态计算停留时间：基础 3000ms，每字 250ms，确保与字数成正比
    const calcDuration = duration ?? Math.max(3000, text.length * 250);
    queueRef.current.push({ id, text, duration: calcDuration });
    processQueue();
  }, [processQueue]);

  return { bubbles, showBubble, registerBubble };
};
