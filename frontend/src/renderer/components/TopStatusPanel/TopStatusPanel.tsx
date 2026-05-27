import React from 'react';
import { useSystemStore } from '../../stores/systemStore';
import './TopStatusPanel.css';

export const TopStatusPanel: React.FC = () => {
  const connectionStatus = useSystemStore((state) => state.connectionStatus);

  // 模拟角色状态文案，后续可从 store 中获取真实状态
  const getStatusText = () => {
    if (connectionStatus === 'connecting') return '正在醒来...';
    if (connectionStatus === 'disconnected') return '睡着了';
    
    // 随机返回一些自然的状态文案
    const statuses = ['在发呆', '有点困', '在等你说话', '刚刚想到你', '今天心情不错'];
    // 这里为了演示简单返回固定值，实际应由后端推送状态
    return '在等你说话';
  };

  return (
    <div className="top-status-panel">
      <div className="status-text">
        <span className={`status-dot ${connectionStatus}`}></span>
        {getStatusText()}
      </div>
    </div>
  );
};
