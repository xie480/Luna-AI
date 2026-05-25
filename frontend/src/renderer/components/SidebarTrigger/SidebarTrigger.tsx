/**
 * Luna AI 侧边栏呼出按钮组件
 * 悬浮在主界面右上角，用于呼出侧边栏
 */
import React from 'react';
import { useSystemStore, SidebarPanelType } from '../../stores/systemStore';
import './SidebarTrigger.css';

/**
 * 侧边栏呼出按钮组件
 * 提供多个快捷按钮，点击后呼出对应面板的侧边栏
 */
export const SidebarTrigger: React.FC = () => {
  const openSidebar = useSystemStore.getState().openSidebar;
  const isSidebarOpen = useSystemStore((state) => state.isSidebarOpen);
  const [isMenuOpen, setIsMenuOpen] = React.useState(false);

  /**
   * 呼出指定面板的侧边栏
   */
  const handleOpenPanel = (panel: SidebarPanelType): void => {
    openSidebar(panel);
    setIsMenuOpen(false);
  };

  return (
    <div className={`sidebar-trigger-container ${isSidebarOpen ? 'hidden' : ''}`}>
      <button
        className={`main-trigger-button ${isMenuOpen ? 'active' : ''}`}
        onClick={() => setIsMenuOpen(!isMenuOpen)}
        title="菜单"
      >
        {'>'}
      </button>
      
      <div className={`sidebar-menu ${isMenuOpen ? 'open' : ''}`}>
        <button
          className="menu-button"
          onClick={() => handleOpenPanel('dag')}
          title="任务流"
        >
          📊
        </button>
        <button
          className="menu-button"
          onClick={() => handleOpenPanel('memory')}
          title="记忆"
        >
          🧠
        </button>
        <button
          className="menu-button"
          onClick={() => handleOpenPanel('settings')}
          title="设置"
        >
          ⚙️
        </button>
        <button
          className="menu-button"
          onClick={() => handleOpenPanel('logs')}
          title="日志"
        >
          📋
        </button>
      </div>
    </div>
  );
};