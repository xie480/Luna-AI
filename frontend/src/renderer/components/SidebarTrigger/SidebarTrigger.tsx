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

  /**
   * 呼出指定面板的侧边栏
   */
  const handleOpenPanel = (panel: SidebarPanelType): void => {
    openSidebar(panel);
  };

  return (
    <div className={`sidebar-trigger ${isSidebarOpen ? 'hidden' : ''}`}>
      <button
        className="trigger-button"
        onClick={() => handleOpenPanel('dag')}
        title="任务流"
      >
        📊
      </button>
      <button
        className="trigger-button"
        onClick={() => handleOpenPanel('memory')}
        title="记忆"
      >
        🧠
      </button>
      <button
        className="trigger-button"
        onClick={() => handleOpenPanel('settings')}
        title="设置"
      >
        ⚙️
      </button>
      <button
        className="trigger-button"
        onClick={() => handleOpenPanel('logs')}
        title="日志"
      >
        📋
      </button>
    </div>
  );
};