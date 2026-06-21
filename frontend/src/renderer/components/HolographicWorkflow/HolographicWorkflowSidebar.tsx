import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE, CHAT_WORKFLOW_NODE_TYPE } from '../../../shared/enum';
import { HolographicNode } from './HolographicNode';
import { HolographicConnections } from './HolographicConnections';
import { HolographicARPanel } from './HolographicARPanel';
import { PanelTransition } from '../PanelTransition/PanelTransition';
import './HolographicWorkflowSidebar.css';

const MIN_WIDTH = 260;
const DEFAULT_WIDTH = 320;
// Max width will be calculated dynamically based on window size (e.g., 40%)

export const HolographicWorkflowSidebar: React.FC = () => {
  const activePlan = useChatWorkflowStore((state) => state.activePlan);
  const nodesByInteractionId = useChatWorkflowStore((state) => state.nodesByInteractionId);
  const isWorkflowDebugDrawerOpen = useChatWorkflowStore((state) => state.isWorkflowDebugDrawerOpen);
  
  // Tie sidebar visibility to the existing systemStore left sidebar state
  // But wait, the prompt said "add a new button to control visibility, right below existing button".
  // Let's create a local state for this specific workflow sidebar visibility
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

  const interactionId = activePlan?.interactionId;
  
  // Wrap nodes initialization in useMemo to prevent dependency arrays from triggering on every render
  const nodes = useMemo(() => {
    return interactionId ? nodesByInteractionId[interactionId] || [] : [];
  }, [interactionId, nodesByInteractionId]);

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

  // 2. Auto Scroll to Active Node
  useEffect(() => {
    if (!scrollRef.current || !activePlan) return;
    
    // Find the currently running node or the last node
    const activeNode = [...nodes].reverse().find(n => n.status === 'running') || nodes[nodes.length - 1];
    
    if (activeNode) {
        setActiveNodeId(activeNode.nodeType);
        // Simple auto-scroll for now. In a real scenario with many nodes, 
        // we'd calculate offset to keep it in the lower 60% of viewport.
        const nodeEl = scrollRef.current.querySelector(`[data-node-type="${activeNode.nodeType}"]`);
        if (nodeEl) {
             nodeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    } else {
        setActiveNodeId(null);
    }
  }, [nodes, activePlan]);

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


  const chatMode = useSystemStore((state) => state.chatMode);

  // Plan-State-Node 模式下隐藏 Phase 8.5 的 HolographicWorkflow 侧边栏
  // 因为 DAG 面板会替代它
  if (chatMode === CHAT_MODE.PLAN_STATE_NODE) {
    return null;
  }

  const hasPlan = activePlan !== null;

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
        <div className="header-title">Orbital Flow</div>
        <div className="header-controls" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {activePlan && <div className={`global-status-indicator ${activePlan.status}`}></div>}
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
                />
            ))}
            
            {/* End Node：只要存在活动计划就始终渲染，确保连线完整贯穿流程收尾阶段 */}
            {activePlan && (
                <HolographicNode
                    type="end"
                    nodeType="workflow_end"
                    status={
                        activePlan.status === 'completed' ? 'succeeded' :
                        activePlan.status === 'failed' ? 'failed' :
                        'pending'
                    }
                    isActive={activePlan.status === 'postprocessing'}
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
