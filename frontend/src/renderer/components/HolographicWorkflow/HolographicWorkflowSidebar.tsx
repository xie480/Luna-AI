import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE, CHAT_WORKFLOW_NODE_TYPE, DAG_NODE_STATUS } from '../../../shared/enum';
import { HolographicNode } from './HolographicNode';
import { HolographicConnections } from './HolographicConnections';
import { HolographicARPanel } from './HolographicARPanel';
import { PanelTransition } from '../PanelTransition/PanelTransition';
import type { ChatNodeStatus } from '../../../shared/types';
import type { ChatNodeProjection } from '../../types/chatWorkflow';
import type { DagPlanProjection, DagStateProjection } from '../../types/dagWorkflow';
import './HolographicWorkflowSidebar.css';

const MIN_WIDTH = 260;
const DEFAULT_WIDTH = 320;
// Max width will be calculated dynamically based on window size (e.g., 40%)

export const HolographicWorkflowSidebar: React.FC = () => {
  // Phase 8.5 日常聊天/极速闲聊模式数据
  const chatActivePlan = useChatWorkflowStore((state) => state.activePlan);
  const nodesByInteractionId = useChatWorkflowStore((state) => state.nodesByInteractionId);
  const isWorkflowDebugDrawerOpen = useChatWorkflowStore((state) => state.isWorkflowDebugDrawerOpen);

  // Phase 9 智能规划模式数据
  const dagActivePlan = useDagWorkflowStore((state) => state.activePlan);
  const dagPanelVisible = useDagWorkflowStore((state) => state.isPanelVisible);

  // 聊天模式
  const chatMode = useSystemStore((state) => state.chatMode);

  const [isVisible, setIsVisible] = useState(true);

  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [arPanelData, setARPanelData] = useState<{
    nodeType: string;
    targetRect: DOMRect;
  } | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 根据聊天模式选择数据源
  const isDagMode = chatMode === CHAT_MODE.PLAN_STATE_NODE;

  /** Phase 8.5 工作流中属于预 DAG 阶段的节点类型集合。
   * 做什么：在 plan_state_node 模式下，SESSION_CONTEXT_LOAD 和 INPUT_RECONSTRUCTION_SIMPLIFIED
   *         是 DAG 引擎之前执行的 LangGraph 节点，它们的事件发布到 chatWorkflowStore 而非 dagWorkflowStore。
   *         需要将这些节点作为"预 DAG 节点"合并到侧边栏节点列表中。
   */
  const PRE_DAG_NODE_TYPES = new Set([
    CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD,
    CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION,
  ]);

  // 日常聊天/闲聊模式的节点数据
  const chatInteractionId = chatActivePlan?.interactionId;
  const chatNodes = useMemo(() => {
    return chatInteractionId ? nodesByInteractionId[chatInteractionId] || [] : [];
  }, [chatInteractionId, nodesByInteractionId]);

  /**
   * 在智能规划模式下，构建合并的节点列表：
   * 1. 从 chatWorkflowStore 提取预 DAG 节点（SESSION_CONTEXT_LOAD、INPUT_RECONSTRUCTION）
   * 2. 从 dagWorkflowStore 提取 DAG State 节点（展示 intent 而非雪花 ID）
   * 3. 按后端执行顺序合并
   *
   * 为什么这样做：预 DAG 节点的事件经 SSE 路由到 chatWorkflowStore，
   *               而 DAG 引擎完成后才向 dagWorkflowStore 发布事件，
   *               侧边栏不能等到 DAG Plan 生成后才显示前两个节点。
   */
  const dagNodes: { nodeType: string; status: ChatNodeStatus | 'pending'; startedAtMs?: number; customLabel?: string }[] = useMemo(() => {
    if (!isDagMode) return [];

    // 1. 从 chatWorkflowStore 提取预 DAG 节点（SESSION_CONTEXT_LOAD、INPUT_RECONSTRUCTION）
    const preDagNodes = chatNodes.filter((n) => PRE_DAG_NODE_TYPES.has(n.nodeType));

    // 如果 DAG Plan 尚未生成，只显示预 DAG 节点（用户发送后即时可见）
    // 为什么这样做：SESSION_CONTEXT_LOAD 和 INPUT_RECONSTRUCTION 在 DAG 引擎之前执行，
    //               它们的事件通过 chatWorkflowStore 传播，但侧边栏不应等到 DAG Plan 生成才渲染
    if (!dagActivePlan) return preDagNodes;

    // 2. 将 DAG State 投影转换为节点格式，使用 intent 作为 customLabel
    //    修复：不再使用雪花 ID 作为节点标签，而是展示 intent 语义描述
    const stateNodes = dagActivePlan.states.map((s) => ({
      nodeType: s.stateId,
      status: (() => {
        if (s.status === DAG_NODE_STATUS.SUCCEEDED) return 'succeeded' as ChatNodeStatus;
        if (s.status === DAG_NODE_STATUS.FAILED) return 'failed' as ChatNodeStatus;
        if (s.status === DAG_NODE_STATUS.RUNNING) return 'running' as ChatNodeStatus;
        if (s.status === DAG_NODE_STATUS.DEGRADED) return 'degraded' as ChatNodeStatus;
        return 'pending' as ChatNodeStatus;
      })(),
      startedAtMs: s.startedAtMs,
      customLabel: s.intent || s.goal || 'State ' + s.orderIndex,
    }));

    // 3. 合并：预 DAG 节点在前，DAG State 节点在后
    return [...preDagNodes, ...stateNodes];
  }, [isDagMode, dagActivePlan, chatNodes]);

  // 统一数据源：智能规划用 dagNodes，其他用 chatNodes
  const interactionId = isDagMode ? dagActivePlan?.planId : chatActivePlan?.interactionId;
  const nodes = isDagMode ? dagNodes : chatNodes;

  // 1. Drag to Resize Logic
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      
      const maxWidth = window.innerWidth * 0.4;
      // Calculate new width (mouse X position relative to left edge, assuming sidebar is docked left)
      // Since it's docked left, the new width is simply e.clientX
      let newWidth = e.clientX;
      
      // If it's floating or offset, we'd need containerRef.current.getBoundingClientRect().left
      
      if (newWidth < MIN_WIDTH) newWidth = MIN_WIDTH;
      if (newWidth > maxWidth) newWidth = maxWidth;
      
      setWidth(newWidth);
    };

    const handleMouseUp = () => {
      if (isDragging) {
        setIsDragging(false);
        // TODO: Persist width to local storage
      }
    };

    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isDragging]);

  // 根据聊天模式判断是否有活跃 Plan
  // 智能规划模式下：有 DAG Plan 或已有预 DAG 节点（SESSION_CONTEXT_LOAD / INPUT_RECONSTRUCTION）时都显示侧边栏
  // 为什么这样做：预 DAG 节点在 DAG 引擎之前执行，侧边栏应即时渲染这些节点
  const hasPlan = isDagMode
    ? (dagActivePlan !== null && dagPanelVisible) || (chatActivePlan !== null && nodes.length > 0)
    : chatActivePlan !== null;

  // 2. Auto Scroll to Active Node
  useEffect(() => {
    if (!scrollRef.current || !hasPlan) return;
    
    // Find the currently running node or the last node
    const activeNode = [...nodes].reverse().find(n => n.status === 'running') || nodes[nodes.length - 1];
    
    if (activeNode) {
        setActiveNodeId(activeNode.nodeType);
        const nodeEl = scrollRef.current.querySelector(`[data-node-type="${activeNode.nodeType}"]`);
        if (nodeEl) {
             nodeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    } else {
        setActiveNodeId(null);
    }
  }, [nodes, hasPlan]);

  // Handle Holographic AR Panel Toggle
  const toggleARPanel = useCallback((nodeType: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const targetRect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    setARPanelData((current) => {
      if (current?.nodeType === nodeType) {
        return null;
      }
      return { nodeType, targetRect };
    });
  }, []);
  
  // Close AR Panel when clicking outside
  useEffect(() => {
      const handleClickOutside = (e: MouseEvent) => {
          if (arPanelData && containerRef.current && !containerRef.current.contains(e.target as Node)) {
              // We are clicking entirely outside the sidebar, maybe close it?
              // Actually, closing on outside click is standard for popovers.
              setARPanelData(null);
          }
      };
      
      // Need a slight delay to prevent the trigger click from immediately closing it
      if (arPanelData) {
          setTimeout(() => {
            window.addEventListener('click', handleClickOutside);
          }, 10);
      }
      
      return () => {
          window.removeEventListener('click', handleClickOutside);
      }
  }, [arPanelData])



  return (
    <>
    {/* Workflow Toggle Button */}
    <button
      className={`sidebar-trigger workflow-trigger ${isVisible && hasPlan ? 'workflow-open' : ''}`}
      onClick={() => setIsVisible(true)}
      disabled={!hasPlan}
      title={hasPlan ? "Open Workflow Panel" : "No active workflow"}
      style={{
        opacity: (hasPlan && isVisible) ? 0 : 1,
        transform: (hasPlan && isVisible) ? 'scale(0.8) translateX(-20px)' : 'scale(1) translateX(0)',
        pointerEvents: (hasPlan && isVisible) ? 'none' : 'auto',
        transition: 'all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275)'
      }}
    >
      <div className="trigger-icon">
        {/* Network / Workflow Icon */}
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
           <circle cx="18" cy="5" r="3" />
           <circle cx="6" cy="12" r="3" />
           <circle cx="18" cy="19" r="3" />
           <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
           <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
        </svg>
      </div>
    </button>

    <div
      className={`holographic-sidebar ${isWorkflowDebugDrawerOpen ? 'debug-open' : ''} ${(!isVisible || !hasPlan) ? 'hidden' : ''}`}
      style={{ width: `${width}px` }}
      ref={containerRef}
    >
      <div className="holographic-background">
          <div className="holographic-grid-overlay"></div>
      </div>
      
      <div className="holographic-header">
        <div className="header-title">{isDagMode ? 'DAG Flow' : 'Orbital Flow'}</div>
        <div className="header-controls" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {hasPlan && <div className={`global-status-indicator ${isDagMode ? (dagActivePlan?.status === 'executing' ? 'running' : dagActivePlan?.status || '') : chatActivePlan?.status || ''}`}></div>}
          <button
            onClick={() => setIsVisible(false)}
            style={{
              background: 'none',
              border: 'none',
              color: '#00ffff',
              cursor: 'pointer',
              fontSize: '18px',
              padding: '0',
              lineHeight: '1',
              opacity: '0.8'
            }}
            title="Minimize Panel"
          >
            ×
          </button>
        </div>
      </div>

      <div className="holographic-canvas" ref={scrollRef}>
        <HolographicConnections nodes={nodes} activeNodeId={activeNodeId} width={width} />
        
        <div className="node-list">
            {/* Start Node */}
            <HolographicNode 
                type="start" 
                nodeType={CHAT_WORKFLOW_NODE_TYPE.MESSAGE_INGRESS} 
                status="succeeded"
                isActive={false}
            />
            
            {nodes.map((node) => (
                <HolographicNode
                    key={node.nodeType}
                    type={getUINodeType(node.nodeType)}
                    nodeType={node.nodeType}
                    status={node.status}
                    isActive={node.nodeType === activeNodeId}
                    onToggleAR={(e) => toggleARPanel(node.nodeType, e)}
                    interactionId={interactionId}
                    customLabel={'customLabel' in node ? (node as any).customLabel : undefined}
                />
            ))}
            
            {/* End Node：只要存在活动计划就始终渲染，确保连线完整贯穿流程收尾阶段 */}
            {hasPlan && (
                <HolographicNode
                    type="end"
                    nodeType="workflow_end"
                    status={(() => {
                        if (isDagMode) {
                            // DAG 模式：根据 dagActivePlan.status 映射
                            if (!dagActivePlan) return 'pending';
                            if (dagActivePlan.status === 'completed' || dagActivePlan.status === 'succeeded') return 'succeeded';
                            if (dagActivePlan.status === 'failed' || dagActivePlan.status === 'terminated') return 'failed';
                            return 'pending';
                        }
                        // 日常聊天模式
                        if (chatActivePlan?.status === 'completed') return 'succeeded';
                        if (chatActivePlan?.status === 'failed') return 'failed';
                        return 'pending';
                    })()}
                    isActive={isDagMode ? false : chatActivePlan?.status === 'postprocessing'}
                />
            )}
        </div>
      </div>

      {/* Resize Handle */}
      <div
        className={`holographic-resize-handle ${isDragging ? 'dragging' : ''}`}
        onMouseDown={handleMouseDown}
      >
        <div className="resize-glow"></div>
      </div>

      {/* 全息投影覆盖层 — 绝对定位脱离 Flex 文档流，避免抢占 canvas 高度 */}
      <div className="holographic-overlay-container">
        <PanelTransition isLoading={!hasPlan}>
          {/* AR Projection Panel */}
          {arPanelData && (
              <HolographicARPanel
                nodeType={arPanelData.nodeType}
                interactionId={interactionId!}
                targetRect={arPanelData.targetRect}
                containerRect={containerRef.current?.getBoundingClientRect()}
                onClose={() => setARPanelData(null)}
              />
          )}
        </PanelTransition>
      </div>
    </div>
    </>
  );
};

// Helper to map backend node types to visual shapes
function getUINodeType(nodeType: string): 'normal' | 'condition' {
    const conditionNodes = [
        CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG,
        CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG
    ] as string[];
    return conditionNodes.includes(nodeType) ? 'condition' : 'normal';
}
