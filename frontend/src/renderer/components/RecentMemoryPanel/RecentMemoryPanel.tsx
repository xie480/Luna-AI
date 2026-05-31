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
import React from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import './RecentMemoryPanel.css';

/**
 * 近期记忆面板组件
 */
export const RecentMemoryPanel: React.FC = () => {
  const recentQA = useSessionStore((state) => state.recentQA);

  if (recentQA.length === 0) {
    return null;
  }

  return (
    <div className="recent-memory-panel">
      <div className="recent-memory-panel-content">
        <div className="panel-header">
          <span className="panel-title">近期记忆</span>
        </div>
        {recentQA.map((qa) => (
          <div key={qa.msgId} className="qa-item">
            <div className="user-label">你</div>
            <div className="user-text">{qa.userContent}</div>
            <div className="luna-label">Luna</div>
            <div className="luna-text">{qa.assistantContent}</div>
          </div>
        ))}
      </div>
    </div>
  );
};
