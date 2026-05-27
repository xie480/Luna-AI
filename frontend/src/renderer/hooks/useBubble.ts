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

  // 缓冲队列和活跃计数
  const queueRef = useRef<QueueItem[]>([]);
  const activeCountRef = useRef(0);
  const MAX_BUBBLES = 3;

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  /**
   * 处理缓冲队列
   * 当活跃气泡数少于最大限制时，从队列头部取出下一个项目进行渲染
   */
  const processQueue = useCallback(() => {
    if (activeCountRef.current >= MAX_BUBBLES || queueRef.current.length === 0) {
      return;
    }

    const item = queueRef.current.shift()!;
    activeCountRef.current++;

    const { id, text, duration } = item;

    // 1. 记录旧位置 (First)
    const prevPositions = new Map<number, number>();
    bubbleElsRef.current.forEach((el, key) => {
      try { prevPositions.set(key, el.getBoundingClientRect().top); } catch (e) { /* 忽略获取失败的元素 */ }
    });

    // 2. 添加新气泡触发渲染 (Last)
    setBubbles(prev => [...prev, { id, text, leaving: false }]);

    // 3. 等待 DOM 更新后执行动画 (Invert & Play)
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

    // 4. 定时销毁
    setTimeout(() => {
      setBubbles(prev => prev.map(b => b.id === id ? { ...b, leaving: true } : b));
      setTimeout(() => {
        setBubbles(prev => prev.filter(b => b.id !== id));
        bubbleElsRef.current.delete(id);
        activeCountRef.current--;
        // 销毁后尝试处理队列中的下一个
        processQueue();
      }, 300); // 等待 CSS 淡出动画完成
    }, duration);
  }, []);

  /**
   * 显示气泡
   * 不立即渲染，而是将请求放入缓冲队列
   * 由 processQueue 控制实际的渲染时机
   *
   * @param text 气泡文本
   * @param duration 可选的自定义停留时间，默认根据字数动态计算
   */
  const showBubble = useCallback((text: string, duration?: number) => {
    const id = bubbleIdCounter.current++;
    // 动态计算停留时间：基础 3000ms，每字 250ms，确保与字数成正比
    const calcDuration = duration ?? Math.max(3000, text.length * 250);
    queueRef.current.push({ id, text, duration: calcDuration });
    processQueue();
  }, [processQueue]);

  return { bubbles, showBubble, registerBubble };
};
