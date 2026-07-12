/**
 * 近期记忆面板组件
 * 做什么：在右上角展示最近 3 轮 Q&A 记录，体现 Luna 对近期对话的“印象”。
 * 为什么这样做：拟人化设计，让用户感觉 Luna 记得刚才聊了什么，同时不干扰主聊天区。
 * 输入输出：
 *   - 从 sessionStore 读取 recentQA 列表
 *   - 无用户交互输出（纯展示）
 * 边界条件：
 *   - recentQA 为空时渲染空状态提示
 *   - 最多展示 3 条记录，超出时自动移除最旧的
 */
import React, { useRef, useEffect } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useHistoryStore } from '../../stores/historyStore';
import { useLongAnswerStore } from '../../stores/longAnswerStore';
import { longAnswerService } from '../../services/longAnswerService';
import { HistoryNavigation } from './HistoryNavigation';
import { CalendarPanel } from './CalendarPanel';
import { PhoneMockup } from './PhoneMockup';
import './RecentMemoryPanel.css';

/**
 * 近期记忆面板组件
 */
export const RecentMemoryPanel: React.FC = () => {
  const recentQA = useSessionStore((state) => state.recentQA);
  const { currentView } = useHistoryStore();
  const contentRef = useRef<HTMLDivElement>(null);

  // 初始加载及数据更新时自动滚动到底部
  useEffect(() => {
    if (contentRef.current && currentView === 'RECENT') {
      // 使用 requestAnimationFrame 确保在 DOM 渲染完成后获取到最新的 scrollHeight
      requestAnimationFrame(() => {
        if (contentRef.current) {
          contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
      });
    }
  }, [recentQA, currentView]);

  const { selectedDate } = useHistoryStore();

  return (
    <div className="recent-memory-wrapper">
      <div className={`recent-memory-panel ${currentView === 'CALENDAR' ? 'calendar-view' : ''} ${selectedDate ? 'phone-view' : ''}`}>
        <HistoryNavigation />
        
        {currentView === 'RECENT' ? (
          <div className="recent-memory-panel-content" ref={contentRef}>
            {recentQA.length > 0 ? (
              /* 渲染层防御性去重：按 msgId 去重，用 Map 以 msgId 为 key 保留最后出现的条目 */
              Array.from(new Map(recentQA.map((qa) => [qa.msgId, qa])).values()).map((qa) => (
                <div key={qa.msgId} className="qa-item">
                  <div className="user-label">你</div>
                  <div className="user-text">{qa.userContent}</div>
                  <div className="luna-label">
                    Luna
                    {qa.hasLongAnswer && qa.longAnswerId && (
                      <button
                        className="action-icon-btn document-icon-btn"
                        style={{ marginLeft: '8px', padding: 0, border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--text-secondary)', zIndex: 100, position: 'relative' }}
                        onClick={async (e) => {
                          e.stopPropagation();
                          e.preventDefault();
                          const id = qa.longAnswerId as string;
                          const { openPanel, updateStatus, byId } = useLongAnswerStore.getState();
                          
                          // 如果 store 中没有该数据，先填充一个占位，保证面板立刻渲染
                          if (!byId[id]) {
                            updateStatus(id, { status: 'PENDING', title: '加载中...' });
                          }
                          openPanel(id);
                          
                          try {
                            const data = await longAnswerService.fetchLongAnswerById(id);
                            if (data) {
                              useLongAnswerStore.getState().updateStatus(id, {
                                status: data.status || 'COMPLETED',
                                markdown: data.content_markdown || '',
                                title: data.title || '整理完成',
                                shortSummary: data.short_summary || '',
                                citations: data.citations || [],
                              });
                            } else {
                               useLongAnswerStore.getState().updateStatus(id, {
                                status: 'FAILED',
                                errorMessage: '未能获取到长回答内容',
                              });
                            }
                          } catch (err) {
                            console.error("Failed to load long answer content:", err);
                            useLongAnswerStore.getState().updateStatus(id, {
                              status: 'FAILED',
                              errorMessage: String(err),
                            });
                          }
                        }}
                        title="查看文档内容"
                        aria-label="查看文档内容"
                      >
                        <svg
                          viewBox="0 0 24 24"
                          width="14"
                          height="14"
                          stroke="currentColor"
                          strokeWidth="2"
                          fill="none"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                          <polyline points="14 2 14 8 20 8"></polyline>
                          <line x1="16" y1="13" x2="8" y2="13"></line>
                          <line x1="16" y1="17" x2="8" y2="17"></line>
                          <polyline points="10 9 9 9 8 9"></polyline>
                        </svg>
                      </button>
                    )}
                  </div>
                  <div className="luna-text">{qa.assistantContent}</div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无近期记忆</div>
            )}
          </div>
        ) : (
          <div className={`flip-scene ${selectedDate ? 'is-flipped' : ''}`}>
            <div className="flip-card">
              {/* 正面：月视图日历 */}
              <div className="flip-face flip-front">
                <CalendarPanel />
              </div>
              
              {/* 反面：手机界面 */}
              <div className="flip-face flip-back">
                <PhoneMockup />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
