import { useState, useRef, useCallback } from 'react';
import gsap from 'gsap';

export interface Bubble {
  id: number;
  text: string;
  leaving: boolean;
}

export const useBubble = () => {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const bubbleElsRef = useRef<Map<number, HTMLDivElement>>(new Map());
  const bubbleIdCounter = useRef(0);

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  const showBubble = useCallback(async (text: string, duration = 5000) => {
    const id = bubbleIdCounter.current++;
    
    // 1. 记录旧位置 (First)
    const prevPositions = new Map<number, number>();
    bubbleElsRef.current.forEach((el, key) => {
      try {
        prevPositions.set(key, el.getBoundingClientRect().top);
      } catch (e) {
        console.warn("Failed to get bounding client rect", e);
      }
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
      }, 300); // 等待 CSS 淡出动画完成
    }, duration);
  }, []);

  return { bubbles, showBubble, registerBubble };
};
