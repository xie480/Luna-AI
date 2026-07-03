import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import rehypeRaw from 'rehype-raw';
import mermaid from 'mermaid';

interface LongAnswerMarkdownProps {
  markdown: string;
  status: string;
}

export const LongAnswerMarkdown: React.FC<LongAnswerMarkdownProps> = ({ markdown, status }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [renderedMarkdown, setRenderedMarkdown] = useState(markdown);

  // Auto-scroll logic
  const isScrolledToBottom = useRef(true);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    // User is considered at bottom if within 80px
    isScrolledToBottom.current = scrollHeight - scrollTop - clientHeight < 80;
  };

  useEffect(() => {
    // Throttle rendering for performance if generating
    let timeoutId: number;
    if (status === 'GENERATING' || status === 'SUMMARY_GENERATING') {
      timeoutId = window.setTimeout(() => {
        setRenderedMarkdown(markdown);
      }, 100);
    } else {
      setRenderedMarkdown(markdown);
    }
    return () => clearTimeout(timeoutId);
  }, [markdown, status]);

  useEffect(() => {
    if (isScrolledToBottom.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [renderedMarkdown]);

  useEffect(() => {
    // Initialize mermaid when completed or periodically if needed.
    // For safety, only render mermaid when completed to avoid breaking mid-stream.
    if (status === 'COMPLETED') {
      try {
        mermaid.initialize({ startOnLoad: false, theme: 'dark' });
        mermaid.run({
          nodes: document.querySelectorAll('.language-mermaid'),
        });
      } catch (e) {
        console.error('Mermaid rendering failed', e);
      }
    }
  }, [renderedMarkdown, status]);

  const isGenerating = status === 'GENERATING' || status === 'SUMMARY_GENERATING';

  return (
    <div 
      className="long-answer-markdown-container" 
      ref={containerRef}
      onScroll={handleScroll}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            if (!inline && match && match[1] === 'mermaid') {
              // Only render mermaid raw code if not completed, else let mermaid run process it
              return (
                <div className={`mermaid ${className}`} {...props}>
                  {String(children).replace(/\n$/, '')}
                </div>
              );
            }
            return !inline ? (
              <pre className="long-answer-code-block">
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            ) : (
              <code className={`long-answer-inline-code ${className || ''}`} {...props}>
                {children}
              </code>
            );
          }
        }}
      >
        {renderedMarkdown}
      </ReactMarkdown>
      
      {isGenerating && (
        <div className="long-answer-loading-cursor">
          <span className="cursor-blink">|</span>
        </div>
      )}
    </div>
  );
};
