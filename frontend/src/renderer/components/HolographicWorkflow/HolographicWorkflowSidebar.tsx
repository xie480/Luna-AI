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
import { useAgentLoopStore } from '../../stores/agentLoopStore';
import { useSystemStore } from '../../stores/systemStore';
import { CHAT_MODE, CHAT_WORKFLOW_NODE_TYPE, DAG_NODE_STATUS, CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import { HolographicNode } from './HolographicNode';
import { HolographicConnections } from './HolographicConnections';
import { HolographicARPanel } from './HolographicARPanel';
import { PanelTransition } from '../PanelTransition/PanelTransition';
import { DagGlobalObjectiveNode } from '../DagWorkflow/DagGlobalObjectiveNode';
import { DagStateNode } from '../DagWorkflow/DagStateNode';
import { DagIconChevronDown, DagIconChevronRight } from '../DagWorkflow/DagIcons';
import type { ChatNodeStatus } from '../../../shared/types';
import type { ChatNodeProjection } from '../../types/chatWorkflow';
import { AgentLoopPanel } from '../AgentLoop/AgentLoopPanel';
import { AgentGoalCard } from '../AgentLoop/AgentGoalCard';
import { AgentPlanHeader } from '../AgentLoop/AgentPlanHeader';
import { AgentBudgetBar } from '../AgentLoop/AgentBudgetBar';
import type { DagPlanProjection, DagStateProjection } from '../../types/dagWorkflow';
import './HolographicWorkflowSidebar.css';

/**
 * AgentLoopPanelEmbedded — 将 AgentLoopPanel 嵌入侧边栏的包装组件。
 * 做什么：在侧边栏内部渲染 AgentLoopPanel，使其占据整个可滚动区域。
 */
const AgentLoopPanelEmbedded: React.FC = () => <AgentLoopPanel />;

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

  /**
   * 全局目标区域的展开/收起状态。
   * 做什么：控制全局目标详细信息在侧边栏中的显示与隐藏。
   * 为什么这样做：全局目标固定在标题栏下方后，用户需要收起详情以获得更多画布空间。
   * 默认值：true（默认展开）。
   */
  const [objectiveExpanded, setObjectiveExpanded] = useState(true);

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
  const isAgentLoopMode = chatMode === CHAT_MODE.AGENT_LOOP;

  // Agent Loop 数据
  const agentLoopActiveLoop = useAgentLoopStore((state) => state.activeLoop);
  const agentLoopPanelVisible = useAgentLoopStore((state) => state.isPanelVisible);
  const agentLoopGoalExpanded = useAgentLoopStore((state) => state.goalExpanded);
  const agentLoopToggleGoalExpanded = useAgentLoopStore((state) => state.toggleGoalExpanded);

  /**
   * 预 DAG 阶段的节点类型集合。
   * 做什么：定义 DAG 引擎之前执行的 Chat Workflow 节点。
   * 为什么这样做：这些节点在 DAG 引擎启动前就需要渲染。
   * 注意：Agent Loop 模式使用 INPUT_RECONSTRUCTION_SIMPLIFIED，需要同时包含。
   */
  const PRE_DAG_NODE_TYPES = new Set([
    CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD,
    CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION,
    CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION_SIMPLIFIED,
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
   * 在智能规划/Agent Loop 模式下，构建预 DAG 节点列表。
   * 为什么这样做：预 DAG 节点（SESSION_CONTEXT_LOAD、INPUT_RECONSTRUCTION 等）
   *               在 DAG/Agent Loop 引擎之前执行，需要即时显示。
   * Agent Loop 模式使用 INPUT_RECONSTRUCTION_SIMPLIFIED 代替 INPUT_RECONSTRUCTION。
   */
  const preDagNodes = useMemo(() => {
    if (!isDagMode && !isAgentLoopMode) return [];
    return chatNodes.filter((n) => PRE_DAG_NODE_TYPES.has(n.nodeType));
  }, [isDagMode, isAgentLoopMode, chatNodes]);

  /**
   * 在智能规划/Agent Loop 模式下，构建后 DAG 节点列表。
   * 做什么：提取 DAG/Agent Loop 引擎之后执行的 Chat Workflow 节点。
   * 为什么这样做：引擎执行完成后，上下文治理、Prompt 装配、LLM 推理、响应持久化等
   *               后半段链路节点需要在侧边栏中作为普通节点正常渲染。
   */
  const postDagNodes = useMemo(() => {
    if (!isDagMode && !isAgentLoopMode) return [];
    return chatNodes.filter((n) => POST_DAG_NODE_TYPES.has(n.nodeType));
  }, [isDagMode, isAgentLoopMode, chatNodes]);

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
  // Agent Loop 模式：有 activeLoop 时显示 AgentLoopPanel，否则回退显示 Chat Workflow 节点
  // （后端发送 EVT_DAG_GOAL_LOCKED 之前，前端需要先展示预处理阶段的 Chat Workflow 节点）
  const hasPlan = isAgentLoopMode
    ? (agentLoopActiveLoop !== null && agentLoopPanelVisible) || (chatActivePlan !== null)
    : isDagMode
      ? (dagActivePlan !== null && dagPanelVisible) || (chatActivePlan !== null && preDagNodes.length > 0)
      : chatActivePlan !== null;

  // Auto Scroll — 追踪最新活跃节点
  // 注意：全局目标已移至固定区域，不再参与滚动追踪
  useEffect(() => {
    if (!scrollRef.current || !hasPlan) return;
    let allNodeTypes: string[];
    if (isDagMode && dagActivePlan) {
      // DAG 模式：预DAG → State → 后DAG
      allNodeTypes = [
        ...preDagNodes.map(n => n.nodeType),
        ...dagActivePlan.states.map(s => s.stateId),
        ...postDagNodes.map(n => n.nodeType),
      ];
    } else if (isAgentLoopMode) {
      // Agent Loop 模式：预处理 → Agent Loop 引擎 → 后处理
      allNodeTypes = [
        ...preDagNodes.map(n => n.nodeType),
        CHAT_WORKFLOW_NODE_TYPE.DAG_ENGINE_AGENT_LOOP,
        ...postDagNodes.map(n => n.nodeType),
      ];
    } else {
      allNodeTypes = nodes.map(n => n.nodeType);
    }
    const activeNode = allNodeTypes[allNodeTypes.length - 1];
    if (activeNode) {
      setActiveNodeId(activeNode);
    }
  }, [nodes, hasPlan, dagActivePlan, postDagNodes, isAgentLoopMode, isDagMode, preDagNodes]);

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

  // 计算 DAG/Agent Loop 模式下的节点列表（用于 HolographicConnections）
  // 注意：全局目标节点已从可滚动区域移除，不再参与连线计算
  const dagConnectionNodes: ChatNodeProjection[] = useMemo(() => {
    if (!isDagMode && !isAgentLoopMode) return preDagNodes as ChatNodeProjection[];
    // 构建虚拟 node 列表供 HolographicConnections 计算连线
    const virtualNodes: ChatNodeProjection[] = [];
    // 预 DAG 节点
    for (const n of preDagNodes) {
      virtualNodes.push(n as ChatNodeProjection);
    }

    // Agent Loop 模式：将 Agent Loop 引擎作为单个节点加入连线列表
    if (isAgentLoopMode) {
      virtualNodes.push({
        nodeType: CHAT_WORKFLOW_NODE_TYPE.DAG_ENGINE_AGENT_LOOP,
        status: agentLoopActiveLoop
          ? (agentLoopActiveLoop.status === 'executing' ? 'running' : agentLoopActiveLoop.status === 'completed' ? 'succeeded' : agentLoopActiveLoop.status === 'terminated' ? 'failed' : 'pending')
          : (chatActivePlan?.status === 'completed' ? 'succeeded' : chatActivePlan?.status === 'failed' ? 'failed' : 'running'),
      } as ChatNodeProjection);
    } else if (isDagMode && dagActivePlan) {
      // DAG 模式：State 节点
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
    }

    // 后 DAG 节点（上下文治理、Prompt 装配、LLM、响应持久化等）
    for (const n of postDagNodes) {
      virtualNodes.push(n as ChatNodeProjection);
    }
    return virtualNodes;
  }, [isDagMode, isAgentLoopMode, dagActivePlan, preDagNodes, postDagNodes, agentLoopActiveLoop, chatActivePlan]);

  // HolographicConnections 使用的节点列表
  const connectionNodes = (isDagMode || isAgentLoopMode) ? dagConnectionNodes : chatNodes;

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
        <div className="header-title">{isAgentLoopMode ? 'Agent Loop' : isDagMode ? 'DAG Flow' : 'Orbital Flow'}</div>
        <div className="header-controls" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {hasPlan && <div className={`global-status-indicator ${isAgentLoopMode && agentLoopActiveLoop ? (agentLoopActiveLoop.status === 'executing' ? 'running' : agentLoopActiveLoop.status) : isDagMode ? (dagActivePlan?.status === 'executing' ? 'running' : dagActivePlan?.status || '') : chatActivePlan?.status || ''}`}></div>}
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

      {/* ═══ 全局目标固定区域（DAG 模式 + Agent Loop 模式）
       * 做什么：将全局目标固定在侧边栏标题栏下方，不随画布滚动。
       * 为什么这样做：全局目标是用户理解当前 Plan 的关键入口，
       *               固定后用户无需滚动画布即可查看任务总览。
       * 视觉约束：通过发光边框和背景色与下方可滚动画布明确区分。
       */}
      {/* Agent Loop 模式：显示全局目标、验收标准、预算（固定区域） */}
      {isAgentLoopMode && agentLoopActiveLoop && (
        <div className={`dag-objective-fixed-area agent-loop-objective ${objectiveExpanded ? 'expanded' : 'collapsed'}`}>
          <div className="dag-objective-fixed-header">
            <span className="dag-objective-fixed-label">全局目标</span>
            <span className="dag-objective-fixed-goal">
              {agentLoopActiveLoop.goal.globalGoal || '（目标待生成）'}
            </span>
            <button
              className={`dag-objective-toggle-btn ${objectiveExpanded ? 'is-expanded' : ''}`}
              onClick={() => setObjectiveExpanded((prev) => !prev)}
              aria-label={objectiveExpanded ? '收起全局目标详情' : '展开全局目标详情'}
              type="button"
            >
              <span className="dag-objective-toggle-text">
                {objectiveExpanded ? '收起' : '展开'}
              </span>
              {objectiveExpanded
                ? <DagIconChevronDown width="12" height="12" />
                : <DagIconChevronRight width="12" height="12" />
              }
            </button>
          </div>
          {objectiveExpanded && (
            <div className="dag-objective-fixed-details">
              <AgentGoalCard
                goal={agentLoopActiveLoop.goal}
                expanded={agentLoopGoalExpanded}
                onToggle={agentLoopToggleGoalExpanded}
              />
              <AgentPlanHeader
                plan={agentLoopActiveLoop.plan}
                completedSteps={agentLoopActiveLoop.plan.steps.filter((s) => s.status === 'passed').length}
              />
              <AgentBudgetBar budget={agentLoopActiveLoop.budget} />
            </div>
          )}
        </div>
      )}

      {isDagMode && dagActivePlan && (
        <div className={`dag-objective-fixed-area ${objectiveExpanded ? 'expanded' : 'collapsed'}`}>
          <div className="dag-objective-fixed-header">
            <span className="dag-objective-fixed-label">全局目标</span>
            <span className="dag-objective-fixed-goal">
              {dagActivePlan.globalObjective.overallGoal || dagActivePlan.planningReason || '（目标待生成）'}
            </span>
            <button
              className={`dag-objective-toggle-btn ${objectiveExpanded ? 'is-expanded' : ''}`}
              onClick={() => setObjectiveExpanded((prev) => !prev)}
              aria-label={objectiveExpanded ? '收起全局目标详情' : '展开全局目标详情'}
              type="button"
            >
              <span className="dag-objective-toggle-text">
                {objectiveExpanded ? '收起' : '展开'}
              </span>
              {objectiveExpanded
                ? <DagIconChevronDown width="12" height="12" />
                : <DagIconChevronRight width="12" height="12" />
              }
            </button>
          </div>
          <div className="dag-objective-fixed-details">
            <DagGlobalObjectiveNode plan={dagActivePlan} />
          </div>
        </div>
      )}

      <div className="holographic-canvas" ref={scrollRef}>
        {/* 连线层 — 统一处理日常聊天和 DAG 模式 */}
        <HolographicConnections nodes={connectionNodes} activeNodeId={activeNodeId} width={width} />
        
        <div className="node-list">
            {/* ═══ 互斥条件分支：Agent Loop > DAG > 日常聊天 ═══ */}
            {isAgentLoopMode ? (
              /* ═══ Agent Loop 模式：pre-nodes → AgentLoopPanel（特殊渲染）→ post-nodes ═══ */
              <>
                {/* 预 Agent Loop 节点（SESSION_CONTEXT_LOAD、INPUT_RECONSTRUCTION_SIMPLIFIED） */}
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

                {/* Agent Loop 引擎节点 — 特殊渲染（类似 DAG 模式的 State 节点）
                 * data-node-type 用于 HolographicConnections 自动检测连线目标。
                 * agent-loop-node-wrapper CSS 类确保左右边距与全局目标面板一致。 */}
                {agentLoopActiveLoop ? (
                  <div
                    className="agent-loop-node-wrapper"
                    data-node-type={CHAT_WORKFLOW_NODE_TYPE.DAG_ENGINE_AGENT_LOOP}
                    style={{ minHeight: 200 }}
                  >
                    <AgentLoopPanelEmbedded />
                  </div>
                ) : (
                  <HolographicNode
                    type="normal"
                    nodeType={CHAT_WORKFLOW_NODE_TYPE.DAG_ENGINE_AGENT_LOOP}
                    status={chatActivePlan?.status === 'completed' ? 'succeeded' : chatActivePlan?.status === 'failed' ? 'failed' : 'running'}
                    isActive={true}
                  />
                )}

                {/* 后 Agent Loop 节点（CONTEXT_GOVERNANCE → PROMPT_ASSEMBLY → MAIN_CHAT_LLM → ...） */}
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
                {hasPlan && (
                  <HolographicNode
                    type="end"
                    nodeType="workflow_end"
                    status={(() => {
                      if (agentLoopActiveLoop?.status === 'completed' || agentLoopActiveLoop?.status === 'completed_with_gaps') return 'succeeded';
                      if (agentLoopActiveLoop?.status === 'terminated' || agentLoopActiveLoop?.status === 'budget_exhausted') return 'failed';
                      if (chatActivePlan?.status === 'completed') return 'succeeded';
                      if (chatActivePlan?.status === 'failed') return 'failed';
                      return 'pending';
                    })()}
                    isActive={false}
                  />
                )}
              </>
            ) : isDagMode && dagActivePlan ? (
              /* ═══ DAG 模式：预DAG节点 + State 节点 ═══ */
              <>

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
              /* ═══ 日常聊天/极速闲聊模式（以及 Agent Loop 无 activeLoop 时的回退） ═══ */
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
