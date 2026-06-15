/**
 * Luna AI 模态窗口组件
 * 用于在屏幕正中央展示任务流、记忆、Prompt管理、设置、日志等面板内容
 * 替代原有的右侧边栏弹出逻辑
 * 支持鼠标拖拽移动位置 + 四角四边边框缩放 + 无背景变暗效果
 *
 * 注意：DebugPanel 诊断面板已移至 index.tsx 顶层渲染，与本组件解耦
 *
 * 关闭动画说明：
 * - 当 isModalOpen 变为 false 时，不会立即 return null
 * - 而是触发内部 closing 状态，播放 250ms 关闭动画
 * - 动画结束后才真正 unmount 组件
 * - 所有动画属性严格限制为 transform + opacity，零重排
 */
import React, { useRef, useCallback, useEffect, useState } from 'react';
import { useSystemStore, ModalPanelType } from '../../stores/systemStore';
import { useSessionStore } from '../../stores/sessionStore';
import { ClothingPanel } from '../ClothingPanel/ClothingPanel';
import { SettingsPanel } from '../Settings/SettingsPanel';
import { PromptPanel } from '../PromptPanel/PromptPanel';
import { MemoryPanel } from '../MemoryPanel/MemoryPanel';
import { KnowledgeBasePanel } from '../KnowledgeBase/KnowledgeBasePanel';
import { UserProfilePanel } from '../UserProfile/UserProfilePanel';
import { MCPPanel } from '../MCPPanel/MCPPanel';
import './Modal.css';

/** 最小窗口尺寸 */
const MIN_WIDTH = 400;
const MIN_HEIGHT = 300;

/** 缩放方向 */
type ResizeDirection = 'n' | 's' | 'w' | 'e' | 'nw' | 'ne' | 'sw' | 'se';

/** 标题映射 */
const PANEL_TITLES: Record<ModalPanelType, string> = {
  dag: '任务流',
  memory: '记忆',
  userProfile: 'Luna眼中的你',
  prompts: 'Prompt 管理',
  knowledge: '知识库',
  settings: '设置',
  logs: '日志',
  clothing: '服装配置',
  mcp: 'MCP',
};

/**
 * 面板内容渲染 — 提取为独立函数，根据 activeModalPanel 渲染对应的子面板
 */
const renderPanelContent = (
  activeModalPanel: ModalPanelType | null,
  activePlan: any,
  systemLogs: any[],
): React.ReactNode => {
  switch (activeModalPanel) {
    case 'dag':
      return activePlan ? (
        <div className="dag-view">
          <div className="plan-header">
            <h3>{activePlan.goal}</h3>
            <span className="plan-id">ID: {activePlan.planId}</span>
          </div>
          <div className="nodes-list">
            {activePlan.nodes.map((node: any) => (
              <div key={node.nodeId} className={`node-item ${node.status}`}>
                <div className="node-header">
                  <span className="node-name">{node.name}</span>
                  <span className="node-status">{node.status}</span>
                </div>
                <div className="node-description">{node.description}</div>
                {node.progress > 0 && (
                  <div className="node-progress">
                    <div className="progress-bar" style={{ width: `${node.progress}%` }} />
                  </div>
                )}
                {node.errorMsg && <div className="node-error">{node.errorMsg}</div>}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="empty-panel">
          <div className="empty-icon">📊</div>
          <div className="empty-text">暂无活跃任务</div>
        </div>
      );
    case 'memory':
      return <MemoryPanel />;
    case 'userProfile':
      return <UserProfilePanel />;
    case 'prompts':
      return <PromptPanel />;
    case 'knowledge':
      return <KnowledgeBasePanel />;
    case 'settings':
      return <SettingsPanel />;
    case 'logs':
      return (
        <div className="logs-view">
          <h3>系统日志</h3>
          <div className="logs-container">
            {systemLogs.map((log, index) => (
              <div key={index} className="log-item">{log}</div>
            ))}
          </div>
        </div>
      );
    case 'clothing':
      return <ClothingPanel />;
    case 'mcp':
      return <MCPPanel />;
    default:
      return null;
  }
};

/**
 * 模态窗口组件
 * 根据当前激活的面板类型渲染对应内容
 * 支持关闭动画：isModalOpen=false 时先播动画再卸载
 */
export const Modal: React.FC = () => {
  // 从 Store 获取状态
  const isModalOpen = useSystemStore((state) => state.isModalOpen);
  const activeModalPanel = useSystemStore((state) => state.activeModalPanel);
  const closeModal = useSystemStore.getState().closeModal;

  // 任务计划和数据
  const activePlan = useSessionStore((state) => state.activePlan);
  const systemLogs = useSystemStore((state) => state.systemLogs);

  const modalRef = useRef<HTMLDivElement>(null);

  // === 关闭动画状态机 ===
  const [closing, setClosing] = useState(false);
  const prevIsOpen = useRef(isModalOpen);

  // 当 Store 通知关闭时，先触发关闭动画
  useEffect(() => {
    if (prevIsOpen.current && !isModalOpen) {
      setClosing(true);
    }
    prevIsOpen.current = isModalOpen;
  }, [isModalOpen]);

  // 关闭动画完成后，清理 closing 状态
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => {
      setClosing(false);
    }, 280); // 与 CSS 动画时长对齐
    return () => clearTimeout(timer);
  }, [closing]);

  // === 拖拽状态 ===
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const [modalPosition, setModalPosition] = useState<{ x: number; y: number } | null>(null);

  // === 缩放状态 ===
  const [isResizing, setIsResizing] = useState(false);
  const resizeDirection = useRef<ResizeDirection | null>(null);
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0, left: 0, top: 0 });

  // === 窗口尺寸 ===
  const [modalSize, setModalSize] = useState<{ w: number; h: number }>({ w: 680, h: 520 });

  /**
   * 根据面板类型获取默认尺寸
   */
  const getDefaultSize = useCallback((panel: ModalPanelType | null): { w: number; h: number } => {
    if (panel === 'prompts') return { w: 1300, h: 700 };
    if (panel === 'userProfile') return { w: 860, h: 680 };
    if (panel === 'settings' || panel === 'memory' || panel === 'knowledge' || panel === 'mcp') {
      return { w: 900, h: 600 };
    }
    return { w: 680, h: 520 };
  }, []);

  /** 打开后重置位置和尺寸 */
  useEffect(() => {
    if (isModalOpen) {
      setModalPosition(null);
      setModalSize(getDefaultSize(activeModalPanel));
    }
  }, [isModalOpen, activeModalPanel, getDefaultSize]);

  // ===========================
  //  拖拽逻辑
  // ===========================
  const handleHeaderMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('.modal-close')) return;
    if (target.closest('.modal-resize-handle')) return;

    setIsDragging(true);
    const rect = modalRef.current?.getBoundingClientRect();
    if (rect) {
      dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }
    e.preventDefault();
  }, []);

  // ===========================
  //  缩放逻辑
  // ===========================
  const handleResizeStart = useCallback(
    (dir: ResizeDirection) => (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      setIsResizing(true);
      resizeDirection.current = dir;
      const rect = modalRef.current!.getBoundingClientRect();
      resizeStart.current = {
        x: e.clientX,
        y: e.clientY,
        w: rect.width,
        h: rect.height,
        left: rect.left,
        top: rect.top,
      };
    },
    [],
  );

  /** 统一处理拖拽和缩放 */
  useEffect(() => {
    if (!isDragging && !isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!modalRef.current) return;

      if (isDragging) {
        const newX = e.clientX - dragOffset.current.x;
        const newY = e.clientY - dragOffset.current.y;
        setModalPosition({ x: newX, y: newY });
      }

      if (isResizing && resizeDirection.current) {
        const dir = resizeDirection.current;
        const rs = resizeStart.current;
        const dx = e.clientX - rs.x;
        const dy = e.clientY - rs.y;
        let newW = rs.w;
        let newH = rs.h;
        let newLeft = rs.left;
        let newTop = rs.top;

        if (dir.includes('e')) newW = Math.max(MIN_WIDTH, rs.w + dx);
        if (dir.includes('w')) {
          newW = Math.max(MIN_WIDTH, rs.w - dx);
          newLeft = rs.left + (rs.w - newW);
        }
        if (dir.includes('s')) newH = Math.max(MIN_HEIGHT, rs.h + dy);
        if (dir.includes('n')) {
          newH = Math.max(MIN_HEIGHT, rs.h - dy);
          newTop = rs.top + (rs.h - newH);
        }

        setModalSize({ w: newW, h: newH });
        setModalPosition({ x: newLeft, y: newTop });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, isResizing]);

  /** 关闭模态窗口时重置位置 */
  useEffect(() => {
    if (!isModalOpen) {
      setModalPosition(null);
    }
  }, [isModalOpen]);

  /** 点击遮罩层关闭 */
  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>): void => {
    if (e.target === e.currentTarget && !isDragging && !isResizing) {
      closeModal();
    }
  };

  /** 渲染缩放把手 */
  const renderResizeHandles = () => (
    <>
      <div className="modal-resize-handle rh-n" onMouseDown={handleResizeStart('n')} />
      <div className="modal-resize-handle rh-s" onMouseDown={handleResizeStart('s')} />
      <div className="modal-resize-handle rh-w" onMouseDown={handleResizeStart('w')} />
      <div className="modal-resize-handle rh-e" onMouseDown={handleResizeStart('e')} />
      <div className="modal-resize-handle rh-nw" onMouseDown={handleResizeStart('nw')} />
      <div className="modal-resize-handle rh-ne" onMouseDown={handleResizeStart('ne')} />
      <div className="modal-resize-handle rh-sw" onMouseDown={handleResizeStart('sw')} />
      <div className="modal-resize-handle rh-se" onMouseDown={handleResizeStart('se')} />
    </>
  );

  const panelTitle = activeModalPanel ? PANEL_TITLES[activeModalPanel] : '';

  // 完全关闭 + 动画结束 => 不渲染任何内容
  if (!isModalOpen && !closing) {
    return null;
  }

  return (
    <div className={`modal-overlay ${closing ? 'modal-overlay-closing' : ''}`} onClick={handleOverlayClick}>
      <div
        className={`modal-container ${modalPosition ? 'has-position' : ''} ${closing ? 'modal-container-closing' : ''}`}
        ref={modalRef}
        style={{
          width: modalSize.w,
          height: modalSize.h,
          ...(modalPosition ? { left: modalPosition.x, top: modalPosition.y } : {}),
        }}
      >
        {/* 边框缩放把手 */}
        {renderResizeHandles()}

        {/* 模态窗口头部 - 可拖拽区域 */}
        <div className="modal-header modal-drag-handle" onMouseDown={handleHeaderMouseDown}>
          <h2 className="modal-title">{panelTitle}</h2>
          <button className="modal-close" onClick={closeModal}>✕</button>
        </div>

        {/* 模态窗口内容区 */}
        <div className="modal-content">
          <div className={`panel ${activeModalPanel === 'dag' ? 'dag-panel' : ''}`}>
            {renderPanelContent(activeModalPanel, activePlan, systemLogs)}
          </div>
        </div>
      </div>
    </div>
  );
};
