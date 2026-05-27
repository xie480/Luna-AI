import React, { useEffect, useRef } from 'react';
import { useBubble } from '../../hooks/useBubble';
import { useSessionStore } from '../../stores/sessionStore';
import './BubbleStack.css';

export const BubbleStack: React.FC = () => {
  const { bubbles, registerBubble, sendReplyAsBubbles } = useBubble();
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const messages = useSessionStore((state) =>
    currentSessionId ? state.messages[currentSessionId] || [] : []
  );
  
  // 记录已经处理过的消息 ID，避免重复显示
  const processedMessageIds = useRef<Set<string>>(new Set());
  // 记录当前正在流式输出的消息 ID
  const streamingMessageId = useRef<string | null>(null);
  // 记录当前流式消息已经处理的文本长度
  const processedLength = useRef<number>(0);

  useEffect(() => {
    if (messages.length === 0) return;

    const lastMessage = messages[messages.length - 1];
    
    // 只处理 assistant 的消息
    if (lastMessage.role !== 'assistant') return;

    const msgId = lastMessage.messageId;

    if (lastMessage.status === 'completed') {
      // 如果消息已完成且未处理过，或者之前是流式但现在完成了（需要处理剩余部分）
      if (!processedMessageIds.current.has(msgId)) {
        const textToProcess = lastMessage.content.substring(processedLength.current);
        if (textToProcess.trim()) {
           sendReplyAsBubbles(textToProcess);
        }
        processedMessageIds.current.add(msgId);
        streamingMessageId.current = null;
        processedLength.current = 0;
      }
    } else if (lastMessage.status === 'streaming') {
      // 处理流式消息
      if (streamingMessageId.current !== msgId) {
        // 新的流式消息开始
        streamingMessageId.current = msgId;
        processedLength.current = 0;
      }

      // 检查是否有新的完整句子可以显示
      const currentContent = lastMessage.content;
      const newContent = currentContent.substring(processedLength.current);
      
      // 简单的分句逻辑，遇到标点符号认为是一句
      const sentenceEndRegex = /[。！？!?~～…\n]/;
      const match = newContent.match(sentenceEndRegex);
      
      if (match && match.index !== undefined) {
        const endIndex = match.index + match[0].length;
        const sentence = newContent.substring(0, endIndex);
        
        if (sentence.trim()) {
          sendReplyAsBubbles(sentence);
        }
        
        processedLength.current += endIndex;
      }
    }
  }, [messages, sendReplyAsBubbles]);

  return (
    <div className="bubble-stack">
      {bubbles.map((bubble) => (
        <div
          key={bubble.id}
          ref={(el) => registerBubble(el, bubble.id)}
          className={`css-chat-bubble ${bubble.leaving ? 'leaving' : ''}`}
        >
          <span className="bubble-avatar">✨</span>
          {bubble.text}
        </div>
      ))}
    </div>
  );
};
