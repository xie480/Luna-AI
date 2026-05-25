/**
 * Luna AI 左侧边栏开关按钮组件
 * 固定在页面左上角，用于控制左侧边栏的展开/收起
 * 类似 ChatGPT 的汉堡菜单按钮
 */
import React from 'react';
import { useSystemStore } from '../../stores/systemStore';
import './SidebarTrigger.css';

/**
 * 左侧边栏开关按钮组件
 * 点击切换左侧边栏的展开/收起状态
 */
export const SidebarTrigger: React.FC = () => {
  // 从 Store 获取状态
  const isLeftSidebarOpen = useSystemStore((state) => state.isLeftSidebarOpen);
  const toggleLeftSidebar = useSystemStore.getState().toggleLeftSidebar;

  /**
   * 处理按钮点击
   * 切换左侧边栏状态
   */
  const handleClick = (): void => {
    toggleLeftSidebar();
  };

  return (
    <button
      className={`sidebar-trigger ${isLeftSidebarOpen ? 'sidebar-open' : ''}`}
      onClick={handleClick}
      title={isLeftSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
      aria-label={isLeftSidebarOpen ? '收起侧边栏' : '展开侧边栏'}
    >
      {/* 汉堡菜单图标 / 关闭图标 */}
      <span className="trigger-icon">
        {isLeftSidebarOpen ? (
          // 关闭图标 (X)
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          // 汉堡菜单图标
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        )}
      </span>
    </button>
  );
};