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
import React from 'react';
import { useBubble } from '../../hooks/useBubble';
import { useSystemStore } from '../../stores/systemStore';
import './BubbleStack.css';

export const BubbleStack: React.FC = () => {
  const { bubbles, registerBubble } = useBubble();
  const showBubbleRender = useSystemStore((state) => state.showBubbleRender);

  return (
    <div
      className="bubble-stack"
      style={{ display: showBubbleRender ? undefined : 'none' }}
    >
      {bubbles.map((bubble) => (
        <div
          key={bubble.id}
          ref={(el) => registerBubble(el, bubble.id)}
          className={`css-chat-bubble selectable-text ${bubble.leaving ? 'leaving' : ''}`}
          data-batch-id={bubble.batchId}
          data-bubble-stage={bubble.stage}
          onMouseDown={(e) => e.stopPropagation()} /* 防止因为拖动背景被拦截 */
        >
          {bubble.text}
        </div>
      ))}
    </div>
  );
};
