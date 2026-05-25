/**
 * Luna AI 侧边栏组件
 * 用于展示 DAG 任务树、记忆面板、设置等复杂视图
 * 通过侧边栏呼出，避免污染主聊天区
 */
import React from 'react';
import { useSystemStore, SidebarPanelType } from '../../stores/systemStore';
import { useSessionStore } from '../../stores/sessionStore';
import './Sidebar.css';

/**
 * 侧边栏组件
 * 支持多面板切换：DAG 任务树、记忆面板、设置
 */
export const Sidebar: React.FC = () => {
  // 从 Store 获取状态
  const isSidebarOpen = useSystemStore((state) => state.isSidebarOpen);
  const activeSidebarPanel = useSystemStore((state) => state.activeSidebarPanel);
  const closeSidebar = useSystemStore.getState().closeSidebar;
  const openSidebar = useSystemStore.getState().openSidebar;

  // 任务计划和记忆数据
  const activePlan = useSessionStore((state) => state.activePlan);
  const memory = useSessionStore((state) => state.memory);

  /**
   * 切换面板
   */
  const handlePanelSwitch = (panel: SidebarPanelType): void => {
    openSidebar(panel);
  };

  /**
   * 关闭侧边栏
   */
  const handleClose = (): void => {
    closeSidebar();
  };

  if (!isSidebarOpen) {
    return null;
  }

  return (
    <div className="sidebar-overlay">
      <div className="sidebar-container">
        {/* 侧边栏头部 */}
        <div className="sidebar-header">
          <div className="sidebar-tabs">
            <button
              className={`sidebar-tab ${activeSidebarPanel === 'dag' ? 'active' : ''}`}
              onClick={() => handlePanelSwitch('dag')}
            >
              任务流
            </button>
            <button
              className={`sidebar-tab ${activeSidebarPanel === 'memory' ? 'active' : ''}`}
              onClick={() => handlePanelSwitch('memory')}
            >
              记忆
            </button>
            <button
              className={`sidebar-tab ${activeSidebarPanel === 'settings' ? 'active' : ''}`}
              onClick={() => handlePanelSwitch('settings')}
            >
              设置
            </button>
            <button
              className={`sidebar-tab ${activeSidebarPanel === 'logs' ? 'active' : ''}`}
              onClick={() => handlePanelSwitch('logs')}
            >
              日志
            </button>
          </div>
          <button className="sidebar-close" onClick={handleClose}>
            ✕
          </button>
        </div>

        {/* 侧边栏内容区 */}
        <div className="sidebar-content">
          {/* DAG 任务树面板 */}
          {activeSidebarPanel === 'dag' && (
            <div className="panel dag-panel">
              {activePlan ? (
                <div className="dag-view">
                  <div className="plan-header">
                    <h3>{activePlan.goal}</h3>
                    <span className="plan-id">ID: {activePlan.planId}</span>
                  </div>
                  <div className="nodes-list">
                    {activePlan.nodes.map((node) => (
                      <div
                        key={node.nodeId}
                        className={`node-item ${node.status}`}
                      >
                        <div className="node-header">
                          <span className="node-name">{node.name}</span>
                          <span className="node-status">{node.status}</span>
                        </div>
                        <div className="node-description">{node.description}</div>
                        {node.progress > 0 && (
                          <div className="node-progress">
                            <div
                              className="progress-bar"
                              style={{ width: `${node.progress}%` }}
                            ></div>
                          </div>
                        )}
                        {node.errorMsg && (
                          <div className="node-error">{node.errorMsg}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="empty-panel">
                  <div className="empty-icon">📊</div>
                  <div className="empty-text">暂无活跃任务</div>
                </div>
              )}
            </div>
          )}

          {/* 记忆面板 */}
          {activeSidebarPanel === 'memory' && (
            <div className="panel memory-panel">
              {memory ? (
                <div className="memory-view">
                  <div className="memory-section">
                    <h4>角色设定</h4>
                    <ul className="memory-list">
                      {memory.persona.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="memory-section">
                    <h4>短期记忆</h4>
                    <ul className="memory-list">
                      {memory.shortTerm.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="memory-section">
                    <h4>长期记忆</h4>
                    <ul className="memory-list">
                      {memory.longTermFacts.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="empty-panel">
                  <div className="empty-icon">🧠</div>
                  <div className="empty-text">暂无记忆数据</div>
                </div>
              )}
            </div>
          )}

          {/* 设置面板 */}
          {activeSidebarPanel === 'settings' && (
            <div className="panel settings-panel">
              <div className="settings-view">
                <h3>系统设置</h3>
                <div className="settings-placeholder">
                  设置功能将在后续阶段实现...
                </div>
              </div>
            </div>
          )}

          {/* 日志面板 */}
          {activeSidebarPanel === 'logs' && (
            <div className="panel logs-panel">
              <div className="logs-view">
                <h3>系统日志</h3>
                <div className="logs-container">
                  {useSystemStore.getState().systemLogs.map((log, index) => (
                    <div key={index} className="log-item">{log}</div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};