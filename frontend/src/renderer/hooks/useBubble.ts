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

  const splitReplyIntoChunks = useCallback((text: string): string[] => {
    if (!text) return [];
    text = String(text).replace(/\s+/g, " ").trim();
    if (!text) return [];

    const sentenceRe = /[^。！？!?~～…]+[。！？!?~～…]?/g;
    const sentences = text.match(sentenceRe) || [text];
    const parts: string[] = [];
    const commaRe = /[^，,、；;]+[，,、；;]?/g;

    for (let s of sentences) {
      s = s.trim();
      if (!s) continue;
      const subs = s.match(commaRe) || [s];
      for (let sub of subs) {
        sub = sub.replace(/[，,、；;]$/u, "").trim();
        if (sub) parts.push(sub);
      }
    }
    return parts;
  }, []);

  const sendReplyAsBubbles = useCallback(async (reply: string, opts: { interval?: number, duration?: number } = {}) => {
    const interval = typeof opts.interval === "number" ? opts.interval : 450;
    const duration = typeof opts.duration === "number" ? opts.duration : 5000;
    const chunks = splitReplyIntoChunks(reply);
    if (!chunks.length) return;

    for (let i = 0; i < chunks.length; i++) {
      showBubble(chunks[i], duration);
      if (i < chunks.length - 1) {
        await new Promise((r) => setTimeout(r, interval));
      }
    }
  }, [showBubble, splitReplyIntoChunks]);

  return { bubbles, showBubble, registerBubble, sendReplyAsBubbles, splitReplyIntoChunks };
};
