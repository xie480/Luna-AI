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
  icon: string;
}

/**
 * 左侧边栏菜单项列表
 */
const MENU_ITEMS: MenuItem[] = [
  { id: 'dag', label: '任务流', icon: '📊' },
  { id: 'memory', label: '记忆', icon: '🧠' },
  { id: 'settings', label: '设置', icon: '⚙️' },
  { id: 'logs', label: '日志', icon: '📋' },
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