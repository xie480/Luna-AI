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

  // 即使 recentQA 为空，如果处于日历视图也需要渲染
  if (recentQA.length === 0 && currentView === 'RECENT') {
    return null;
  }

  return (
    <>
      <div className={`recent-memory-panel ${currentView === 'CALENDAR' ? 'calendar-view' : ''}`}>
        <HistoryNavigation />
        
        {currentView === 'RECENT' ? (
          <div className="recent-memory-panel-content" ref={contentRef}>
            {recentQA.length > 0 ? (
              recentQA.map((qa) => (
                <div key={qa.msgId} className="qa-item">
                  <div className="user-label">你</div>
                  <div className="user-text">{qa.userContent}</div>
                  <div className="luna-label">Luna</div>
                  <div className="luna-text">{qa.assistantContent}</div>
                </div>
              ))
            ) : (
              <div className="empty-state">暂无近期记忆</div>
            )}
          </div>
        ) : (
          <CalendarPanel />
        )}
      </div>
      
      {/* 手机界面布局剥离：在日历面板外部独立渲染 */}
      {currentView === 'CALENDAR' && <PhoneMockupContainer />}
    </>
  );
};

// 独立的手机容器组件
const PhoneMockupContainer: React.FC = () => {
  const { selectedDate } = useHistoryStore();
  
  if (!selectedDate) return null;
  
  return (
    <div className="phone-mockup-external-container">
      <PhoneMockup />
    </div>
  );
};
