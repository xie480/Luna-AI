/**
 * Luna AI 左侧边栏组件
 * 提供类似 ChatGPT 的左侧导航菜单
 * 点击菜单项时打开居中模态窗口展示对应内容
 *
 * 互斥规则：
 * - 诊断面板 ('debug') 与模态窗口严格互斥
 * - 点击诊断面板时自动关闭模态窗口
 * - 点击其他菜单项时自动关闭诊断面板
 * - 确保同一时间只有一个面板处于激活可见状态
 */
import React, { useState } from 'react';
import { useSystemStore, ModalPanelType } from '../../stores/systemStore';
import './Sidebar.css';

/**
 * 菜单项配置
 */
interface MenuItem {
  id: ModalPanelType | 'live2d-config' | 'debug';
  label: string;
  icon: React.ReactNode;
  subItems?: {
    id: 'transform' | 'tracking';
    label: string;
  }[];
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
    id: 'prompts',
    label: 'Prompt 管理',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6"></polyline>
        <polyline points="8 6 2 12 8 18"></polyline>
      </svg>
    ),
  },
  {
    id: 'live2d-config',
    label: '立绘初始化配置',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 20.5a8.3 8.3 0 0 1-3-1.5 8.3 8.3 0 0 1-3-3 8.3 8.3 0 0 1-1.5-3 8.3 8.3 0 0 1 0-6 8.3 8.3 0 0 1 1.5-3 8.3 8.3 0 0 1 3-1.5 8.3 8.3 0 0 1 6 0 8.3 8.3 0 0 1 3 1.5 8.3 8.3 0 0 1 1.5 3 8.3 8.3 0 0 1 0 6 8.3 8.3 0 0 1-1.5 3 8.3 8.3 0 0 1-3 3 8.3 8.3 0 0 1-3 1.5z"></path>
        <path d="M12 16v-4"></path>
        <path d="M12 8h.01"></path>
      </svg>
    ),
    subItems: [
      { id: 'transform', label: '立绘配置' },
      { id: 'tracking', label: '鼠标追踪配置' },
    ],
  },
  {
    id: 'clothing',
    label: '服装配置',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 5L4 9h3l2-4h6l2 4h3l-2-4H6z"/>
        <path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/>
        <path d="M9 17l3-2 3 2"/>
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
  {
    id: 'settings',
    label: '设置',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3"></circle>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
      </svg>
    ),
  },
  {
    id: 'debug',
    label: '诊断面板',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21.21 15.89A10 10 0 1 1 8 2.83"></path>
        <path d="M22 12A10 10 0 0 0 12 2v10z"></path>
      </svg>
    ),
  },
];

/**
 * 左侧边栏组件
 * 支持平滑展开/收起动画
 * 点击菜单项打开模态窗口或诊断面板
 * 严格保证同一时间只有一个面板处于激活可见状态
 */
export const Sidebar: React.FC = () => {
  // 从 Store 获取状态
  const isLeftSidebarOpen = useSystemStore((state) => state.isLeftSidebarOpen);
  const setLive2dConfigMode = useSystemStore((state) => state.setLive2dConfigMode);

  const [expandedMenu, setExpandedMenu] = useState<string | null>(null);

  /**
   * 处理菜单项点击
   * 严格实施互斥规则：
   * 1. 点击诊断面板 → 关闭模态窗口，打开诊断面板
   * 2. 点击其他菜单项 → 关闭诊断面板，打开对应的模态窗口
   * 3. 点击子菜单项 → 仅设置 Live2D 配置模式，不涉及面板切换
   */
  const handleMenuClick = (item: MenuItem): void => {
    if (item.subItems) {
      setExpandedMenu(expandedMenu === item.id ? null : item.id);
      return;
    }

    if (item.id === 'debug') {
      // 打开诊断面板时，确保模态窗口已关闭
      useSystemStore.getState().closeModal();
      useSystemStore.getState().setDiagnosticOpen(true);
    } else {
      // 打开其他模态窗口时，确保诊断面板已关闭
      useSystemStore.getState().setDiagnosticOpen(false);
      useSystemStore.getState().openModal(item.id as ModalPanelType);
    }
  };

  const handleSubMenuClick = (subId: 'transform' | 'tracking') => {
    setLive2dConfigMode(subId);
  };

  return (
    <div className={`left-sidebar ${isLeftSidebarOpen ? 'open' : 'closed'}`}>
      {/* 侧边栏头部 */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <span className="logo-icon">😸</span>
          <span className="logo-text">Luna</span>
        </div>
      </div>

      {/* 侧边栏菜单 */}
      <nav className="sidebar-menu">
        {MENU_ITEMS.map((item) => (
          <div key={item.id} className="sidebar-menu-group">
            <button
              className={`sidebar-menu-item ${expandedMenu === item.id ? 'expanded' : ''}`}
              onClick={() => handleMenuClick(item)}
              title={item.label}
            >
              <span className="menu-icon">{item.icon}</span>
              <span className="menu-label">{item.label}</span>
              {item.subItems && (
                <span className="menu-arrow">
                  {expandedMenu === item.id ? '▼' : '▶'}
                </span>
              )}
            </button>
            {item.subItems && expandedMenu === item.id && (
              <div className="sidebar-sub-menu">
                {item.subItems.map((sub) => (
                  <button
                    key={sub.id}
                    className="sidebar-sub-menu-item"
                    onClick={() => handleSubMenuClick(sub.id)}
                  >
                    {sub.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </nav>

      {/* 侧边栏底部 */}
      <div className="sidebar-footer">
        <div className="version-info">v0.1.0</div>
      </div>
    </div>
  );
};
