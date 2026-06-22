/**
 * HolographicWorkflowSidebar — 全息工作流侧边栏。
 * 做什么：统一处理日常聊天/极速闲聊/智能规划三种模式的工作流可视化。
 *         日常聊天模式渲染扁平 HolographicNode 节点列表；
 *         智能规划模式将全局目标和 State 作为流程图节点嵌入 .node-list，
 *         由 HolographicConnections 自动绘制连线。
 * 为什么这样做：State 和全局目标需要作为流程图节点的一部分融入现有连线系统。
 * 输入输出：数据来源为 chatWorkflowStore（日常聊天）和 dagWorkflowStore（智能规划）。
 * 边界条件：无活跃 Plan 时侧边栏隐藏。
 * 异常行为：无。
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE, CHAT_WORKFLOW_NODE_TYPE, DAG_NODE_STATUS, CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import { HolographicNode } from './HolographicNode';
import { HolographicConnections } from './HolographicConnections';
import { HolographicARPanel } from './HolographicARPanel';
import { PanelTransition } from '../PanelTransition/PanelTransition';
import { DagGlobalObjectiveNode } from '../DagWorkflow/DagGlobalObjectiveNode';
import { DagStateNode } from '../DagWorkflow/DagStateNode';
import type { ChatNodeStatus } from '../../../shared/types';
import type { ChatNodeProjection } from '../../types/chatWorkflow';
import type { DagPlanProjection, DagStateProjection } from '../../types/dagWorkflow';
import './HolographicWorkflowSidebar.css';

const MIN_WIDTH = 260;
const DEFAULT_WIDTH = 320;

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

  const isDagMode = chatMode === CHAT_MODE.PLAN_STATE_NODE;

  /**
   * 预 DAG 阶段的节点类型集合。
   * 做什么：定义 DAG 引擎之前执行的 Chat Workflow 节点。
   * 为什么这样做：这些节点在 DAG 引擎启动前就需要渲染。
   */
  const PRE_DAG_NODE_TYPES = new Set([
    CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD,
    CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION,
  ]);

  /**
   * 后 DAG 阶段的节点类型集合。
   * 做什么：定义 DAG 引擎之后执行的 Chat Workflow 节点。
   * 为什么这样做：DAG 引擎执行完成后，后半段链路节点需要在侧边栏中正常渲染，
   *               而不是只渲染 State 节点就结束了。
   */
  const POST_DAG_NODE_TYPES = new Set([
    CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE,
    CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY,
    CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM,
    CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE,
    CHAT_WORKFLOW_NODE_TYPE.FINALIZE,
  ]);

  // 日常聊天/闲聊模式的节点数据
  const chatInteractionId = chatActivePlan?.interactionId;
  const chatNodes = useMemo(() => {
    return chatInteractionId ? nodesByInteractionId[chatInteractionId] || [] : [];
  }, [chatInteractionId, nodesByInteractionId]);

  /**
   * 在智能规划模式下，构建预 DAG 节点列表。
   * 为什么这样做：预 DAG 节点在 DAG 引擎之前执行，需要即时显示。
   */
  const preDagNodes = useMemo(() => {
    if (!isDagMode) return [];
    return chatNodes.filter((n) => PRE_DAG_NODE_TYPES.has(n.nodeType));
  }, [isDagMode, chatNodes]);

  /**
   * 在智能规划模式下，构建后 DAG 节点列表。
   * 做什么：提取 DAG 引擎之后执行的 Chat Workflow 节点。
   * 为什么这样做：DAG 引擎完成后，上下文治理、Prompt 装配、LLM 推理、响应持久化等
   *               后半段链路节点需要在侧边栏中作为普通节点正常渲染。
   */
  const postDagNodes = useMemo(() => {
    if (!isDagMode) return [];
    return chatNodes.filter((n) => POST_DAG_NODE_TYPES.has(n.nodeType));
  }, [isDagMode, chatNodes]);

  // 统一数据源
  const interactionId = isDagMode ? dagActivePlan?.planId : chatActivePlan?.interactionId;
  const nodes = isDagMode ? preDagNodes : chatNodes;

  // Drag to Resize
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      const maxWidth = window.innerWidth * 0.4;
      let newWidth = e.clientX;
      if (newWidth < MIN_WIDTH) newWidth = MIN_WIDTH;
      if (newWidth > maxWidth) newWidth = maxWidth;
      setWidth(newWidth);
    };

    const handleMouseUp = () => {
      if (isDragging) setIsDragging(false);
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

  // 是否有活跃 Plan
  const hasPlan = isDagMode
    ? (dagActivePlan !== null && dagPanelVisible) || (chatActivePlan !== null && preDagNodes.length > 0)
    : chatActivePlan !== null;

  // Auto Scroll — 追踪最新活跃节点
  useEffect(() => {
    if (!scrollRef.current || !hasPlan) return;
    const allNodeTypes = isDagMode && dagActivePlan
      ? [
          'dag_global_objective',
          ...preDagNodes.map(n => n.nodeType),
          ...dagActivePlan.states.map(s => s.stateId),
          ...postDagNodes.map(n => n.nodeType),
        ]
      : nodes.map(n => n.nodeType);
    const activeNode = allNodeTypes[allNodeTypes.length - 1];
    if (activeNode) {
      setActiveNodeId(activeNode);
    }
  }, [nodes, hasPlan, dagActivePlan, postDagNodes]);

  // AR Panel
  const toggleARPanel = useCallback((nodeType: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const targetRect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    setARPanelData((current) => {
      if (current?.nodeType === nodeType) return null;
      return { nodeType, targetRect };
    });
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (arPanelData && containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setARPanelData(null);
      }
    };
    if (arPanelData) {
      setTimeout(() => { window.addEventListener('click', handleClickOutside); }, 10);
    }
    return () => { window.removeEventListener('click', handleClickOutside); };
  }, [arPanelData]);

  // 计算 DAG 模式下的节点列表（用于 HolographicConnections）
  const dagConnectionNodes: ChatNodeProjection[] = useMemo(() => {
    if (!isDagMode || !dagActivePlan) return preDagNodes as ChatNodeProjection[];
    // 构建虚拟 node 列表供 HolographicConnections 计算连线
    const virtualNodes: ChatNodeProjection[] = [];
    // 全局目标节点
    virtualNodes.push({
      nodeType: 'dag_global_objective',
      status: dagActivePlan.status === 'executing' ? 'running' : dagActivePlan.status === 'completed' ? 'succeeded' : 'pending',
    } as ChatNodeProjection);
    // 预 DAG 节点
    for (const n of preDagNodes) {
      virtualNodes.push(n as ChatNodeProjection);
    }
    // State 节点
    for (const s of dagActivePlan.states) {
      virtualNodes.push({
        nodeType: s.stateId,
        status: (() => {
          if (s.status === DAG_NODE_STATUS.SUCCEEDED) return 'succeeded';
          if (s.status === DAG_NODE_STATUS.FAILED) return 'failed';
          if (s.status === DAG_NODE_STATUS.RUNNING) return 'running';
          if (s.status === DAG_NODE_STATUS.DEGRADED) return 'degraded';
          return 'pending';
        })(),
      } as ChatNodeProjection);
    }
    // 后 DAG 节点（上下文治理、Prompt 装配、LLM、响应持久化等）
    for (const n of postDagNodes) {
      virtualNodes.push(n as ChatNodeProjection);
    }
    return virtualNodes;
  }, [isDagMode, dagActivePlan, preDagNodes, postDagNodes]);

  // HolographicConnections 使用的节点列表
  const connectionNodes = isDagMode ? dagConnectionNodes : chatNodes;

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
        {/* 连线层 — 统一处理日常聊天和 DAG 模式 */}
        <HolographicConnections nodes={connectionNodes} activeNodeId={activeNodeId} width={width} />
        
        <div className="node-list">
            {/* ═══ DAG 模式：全局目标 + 预DAG节点 + State 节点 ═══ */}
            {isDagMode && dagActivePlan ? (
              <>
                {/* 全局目标节点（流程图最上方） */}
                <DagGlobalObjectiveNode plan={dagActivePlan} />

                {/* 预 DAG 节点（SESSION_CONTEXT_LOAD、INPUT_RECONSTRUCTION） */}
                {preDagNodes.map((node) => (
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

                {/* State 节点列表（作为流程图节点，用连线连接） */}
                {dagActivePlan.states.map((state) => (
                  <DagStateNode key={state.stateId} state={state} />
                ))}

                {/* 后 DAG 节点（上下文治理、Prompt 装配、LLM、响应持久化等） */}
                {postDagNodes.map((node) => (
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

                {/* End Node */}
                <HolographicNode
                  type="end"
                  nodeType="workflow_end"
                  status={(() => {
                    if (dagActivePlan.status === 'completed') return 'succeeded';
                    if (dagActivePlan.status === 'failed' || dagActivePlan.status === 'terminated') return 'failed';
                    return 'pending';
                  })()}
                  isActive={false}
                />
              </>
            ) : (
              /* ═══ 日常聊天/极速闲聊模式 ═══ */
              <>
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
                
                {hasPlan && (
                    <HolographicNode
                        type="end"
                        nodeType="workflow_end"
                        status={(() => {
                            if (chatActivePlan?.status === 'completed') return 'succeeded';
                            if (chatActivePlan?.status === 'failed') return 'failed';
                            return 'pending';
                        })()}
                        isActive={chatActivePlan?.status === 'postprocessing'}
                    />
                )}
              </>
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

      {/* 全息投影覆盖层 */}
      <div className="holographic-overlay-container">
        <PanelTransition isLoading={!hasPlan}>
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
