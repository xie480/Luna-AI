/**
 * Luna AI 左侧边栏组件
 * 提供类似 ChatGPT 的左侧导航菜单
 * 点击菜单项时打开居中模态窗口展示对应内容
 */
import React from 'react';
import { useSystemStore, ModalPanelType } from '../../stores/systemStore';
import './Sidebar.css';

/**
 * 菜单项配置
 */
interface MenuItem {
  id: ModalPanelType;
  label: string;
  icon: React.ReactNode;
}

/**
 * 左侧边栏菜单项列表
 */
const MENU_ITEMS: MenuItem[] = [
  {
    id: 'dag',
    label: '任务流',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
        <line x1="9" y1="3" x2="9" y2="21"></line>
        <line x1="9" y1="9" x2="21" y2="9"></line>
        <line x1="9" y1="15" x2="21" y2="15"></line>
      </svg>
    ),
  },
  {
    id: 'memory',
    label: '记忆',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
      </svg>
    ),
  },
  {
    id: 'settings',
    label: '设置',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3"></circle>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
      </svg>
    ),
  },
  {
    id: 'logs',
    label: '日志',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
        <polyline points="10 9 9 9 8 9"></polyline>
      </svg>
    ),
  },
];

/**
 * 左侧边栏组件
 * 支持平滑展开/收起动画
 * 点击菜单项打开模态窗口
 */
export const Sidebar: React.FC = () => {
  // 从 Store 获取状态
  const isLeftSidebarOpen = useSystemStore((state) => state.isLeftSidebarOpen);
  const openModal = useSystemStore.getState().openModal;

  /**
   * 处理菜单项点击
   * 打开对应的模态窗口面板
   */
  const handleMenuClick = (panel: ModalPanelType): void => {
    openModal(panel);
  };

  return (
    <div className={`left-sidebar ${isLeftSidebarOpen ? 'open' : 'closed'}`}>
      {/* 侧边栏头部 */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <span className="logo-icon">🌙</span>
          <span className="logo-text">Luna AI</span>
        </div>
      </div>

      {/* 侧边栏菜单 */}
      <nav className="sidebar-menu">
        {MENU_ITEMS.map((item) => (
          <button
            key={item.id}
            className="sidebar-menu-item"
            onClick={() => handleMenuClick(item.id)}
            title={item.label}
          >
            <span className="menu-icon">{item.icon}</span>
            <span className="menu-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* 侧边栏底部 */}
      <div className="sidebar-footer">
        <div className="version-info">v0.1.0</div>
      </div>
    </div>
  );
};