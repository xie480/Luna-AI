/**
 * Luna AI 模态窗口组件
 * 用于在屏幕正中央展示任务流、记忆、设置、日志等面板内容
 * 替代原有的右侧边栏弹出逻辑
 * 支持鼠标拖拽移动位置
 */
import React, { useRef, useCallback, useEffect, useState } from 'react';
import { useSystemStore, ModalPanelType } from '../../stores/systemStore';
import { useSessionStore } from '../../stores/sessionStore';
import { ClothingPanel } from '../ClothingPanel/ClothingPanel';
import './Modal.css';

/**
 * 模态窗口组件
 * 根据当前激活的面板类型渲染对应内容
 */
export const Modal: React.FC = () => {
  // 从 Store 获取状态
  const isModalOpen = useSystemStore((state) => state.isModalOpen);
  const activeModalPanel = useSystemStore((state) => state.activeModalPanel);
  const closeModal = useSystemStore.getState().closeModal;

  // 任务计划和记忆数据
  const activePlan = useSessionStore((state) => state.activePlan);
  const memory = useSessionStore((state) => state.memory);
  const systemLogs = useSystemStore((state) => state.systemLogs);

  // 拖拽状态
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const modalRef = useRef<HTMLDivElement>(null);
  const [modalPosition, setModalPosition] = useState<{ x: number; y: number } | null>(null);
  // 记录拖拽开始时的位置，用于计算相对于弹窗初始位置的偏移
  const initialPositionRef = useRef({ x: 0, y: 0 });

  /**
   * 处理遮罩层点击
   * 点击遮罩层关闭模态窗口
   */
  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (e.target === e.currentTarget && !isDragging) {
      closeModal();
    }
  };

  /**
   * 开始拖拽
   */
  const handleHeaderMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    // 仅响应鼠标左键
    if (e.button !== 0) return;
    // 如果点击的是关闭按钮，不触发拖拽
    const target = e.target as HTMLElement;
    if (target.closest('.modal-close')) return;

    setIsDragging(true);
    const rect = modalRef.current?.getBoundingClientRect();
    if (rect) {
      dragOffset.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };
      // 如果已有自定义位置，记录当前位置；否则使用 rect 计算居中位置
      initialPositionRef.current = {
        x: rect.left,
        y: rect.top,
      };
    }
    e.preventDefault();
  }, []);

  /**
   * 全局鼠标移动和释放监听
   */
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!modalRef.current) return;
      const newX = e.clientX - dragOffset.current.x;
      const newY = e.clientY - dragOffset.current.y;
      setModalPosition({ x: newX, y: newY });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  // 关闭模态窗口时重置位置
  useEffect(() => {
    if (!isModalOpen) {
      setModalPosition(null);
    }
  }, [isModalOpen]);

  /**
   * 获取当前面板的标题
   */
  const getPanelTitle = (panel: ModalPanelType | null): string => {
    switch (panel) {
      case 'dag':
        return '任务流';
      case 'memory':
        return '记忆';
      case 'settings':
        return '设置';
      case 'logs':
        return '日志';
      case 'clothing':
        return '服装配置';
      default:
        return '';
    }
  };

  // 模态窗口未打开时不渲染
  if (!isModalOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div
        className={`modal-container ${modalPosition ? 'has-position' : ''}`}
        ref={modalRef}
        style={modalPosition ? { left: modalPosition.x, top: modalPosition.y } : undefined}
      >
        {/* 模态窗口头部 - 可拖拽区域 */}
        <div
          className="modal-header modal-drag-handle"
          onMouseDown={handleHeaderMouseDown}
        >
          <h2 className="modal-title">{getPanelTitle(activeModalPanel)}</h2>
          <button className="modal-close" onClick={closeModal}>
            ✕
          </button>
        </div>

        {/* 模态窗口内容区 */}
        <div className="modal-content">
          {/* DAG 任务树面板 */}
          {activeModalPanel === 'dag' && (
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
          {activeModalPanel === 'memory' && (
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
          {activeModalPanel === 'settings' && (
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
          {activeModalPanel === 'logs' && (
            <div className="panel logs-panel">
              <div className="logs-view">
                <h3>系统日志</h3>
                <div className="logs-container">
                  {systemLogs.map((log, index) => (
                    <div key={index} className="log-item">{log}</div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 服装配置面板 */}
          {activeModalPanel === 'clothing' && (
            <div className="panel clothing-panel">
              <ClothingPanel />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
