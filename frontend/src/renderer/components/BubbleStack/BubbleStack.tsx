/**
 * Luna AI 气泡栈组件
 * 负责展示聊天气泡，采用独立气泡策略（streaming_rendering_plan.md §3.3 策略 A）
 *
 * 重构说明（根据 streaming_rendering_plan.md）：
 * - 废弃：从 sessionStore 监听消息变化 + 前端 splitReplyIntoChunks 分句逻辑。
 * - 废弃：sendReplyAsBubbles 批量发送逻辑（拆分移至后端 stream_parser.py）。
 * - 采用：监听 window 自定义事件 luna:show-bubble，直接调用 showBubble 渲染。
 * - 后端已按标点断句并下发语义完整的句子，前端无需再分句。
 */
import React, { useEffect } from 'react';
import { useBubble } from '../../hooks/useBubble';
import './BubbleStack.css';

interface ShowBubbleEventDetail {
  text: string;
  duration?: number;
}

export const BubbleStack: React.FC = () => {
  const { bubbles, registerBubble, showBubble } = useBubble();

  /**
   * 监听 wsManager 分发的 luna:show-bubble 事件
   * 直接以独立气泡策略渲染每个文本块
   */
  useEffect(() => {
    const handleShowBubble = (e: Event) => {
      const customEvent = e as CustomEvent<ShowBubbleEventDetail>;
      const { text, duration } = customEvent.detail;
      if (!text || !text.trim()) return;
      showBubble(text, duration ?? Math.max(3000, text.length * 200));
    };

    window.addEventListener('luna:show-bubble', handleShowBubble);
    return () => {
      window.removeEventListener('luna:show-bubble', handleShowBubble);
    };
  }, [showBubble]);

  return (
    <div className="bubble-stack">
      {bubbles.map((bubble) => (
        <div
          key={bubble.id}
          ref={(el) => registerBubble(el, bubble.id)}
          className={`css-chat-bubble ${bubble.leaving ? 'leaving' : ''}`}
        >
          {bubble.text}
        </div>
      ))}
    </div>
  );
};
