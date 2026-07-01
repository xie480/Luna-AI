/**
 * DagWorkflowPanel — DAG 深度工作流主面板。
 * 做什么：作为 DAG 可视化的顶层容器，组合全局信息栏、画布和搜索栏。
 *         全局目标区域固定在面板标题栏下方，不随画布滚动，
 *         并提供收起/展开按钮控制其详细信息的显示。
 * 为什么这样做：Plan-State-Node 模式需要独立的面板来承载四层嵌套的可视化结构；
 *               全局目标作为核心摘要信息需要始终可见且不被画布滚动影响。
 * 输入输出：数据来源为 dagWorkflowStore.activePlan，仅在 plan_state_node 模式下渲染。
 * 边界条件：activePlan 为 null 时展示空状态提示。
 * 异常行为：无。
 */
import React, { useState, useCallback } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { useTaskStateStore } from '../../stores/taskStateStore';
import { DagGlobalInfoBar } from './DagGlobalInfoBar';
import { DagCanvas } from './DagCanvas';
import { TaskControlBar } from './TaskControlBar';
import { DagStateGroup } from './DagStateGroup';
import { DagConnections } from './DagConnections';
import { DagSearchBar } from './DagSearchBar';
import { DagIconX, DagIconTarget, DagIconChevronDown, DagIconChevronRight } from './DagIcons';
import './DagWorkflowPanel.css';

/**
 * DAG 工作流主面板组件。
 * 做什么：渲染 DAG 面板的完整布局，包含固定工具栏、固定全局目标区域和可滑动画布。
 * 为什么这样做：全局目标区域需要与画布区域在视觉和交互上完全隔离。
 */
export const DagWorkflowPanel: React.FC = () => {
  const activePlan = useDagWorkflowStore((state) => state.activePlan);
  const clearPlan = useDagWorkflowStore((state) => state.clearPlan);

  /**
   * 全局目标区域的展开/收起状态。
   * 做什么：控制全局目标详细信息的显示与隐藏。
   * 为什么这样做：用户需要在关注画布节点时收起全局目标以获得更多可视空间。
   * 默认值：true（默认展开）。
   */
  const [objectiveExpanded, setObjectiveExpanded] = useState(true);

  /**
   * 切换全局目标区域的展开/收起状态。
   */
  const toggleObjective = useCallback(() => {
    setObjectiveExpanded((prev) => !prev);
  }, []);

  return (
    <div className="dag-workflow-panel">
      {/* 顶部工具栏 — 固定不可滚动 */}
      <div className="dag-panel-toolbar">
        <div className="dag-panel-toolbar-left">
          <span className="dag-panel-title">DAG Workflow</span>
          {activePlan && (
            <span style={{
              fontFamily: "'Courier New', Courier, monospace",
              fontSize: '11px',
              color: 'rgba(255, 255, 255, 0.3)',
              letterSpacing: '0.5px',
            }}>
              Trace: {activePlan.traceId?.slice(-8) || 'N/A'}
            </span>
          )}
        </div>
        <button
          className="dag-panel-close-btn"
          onClick={clearPlan}
          aria-label="关闭 DAG 面板"
          type="button"
        >
          <DagIconX width="14" height="14" />
        </button>
      </div>

      {/* ═══ Phase 10 任务控制栏 — 固定在顶部工具栏下方 ═══
       * 做什么：当有活跃任务时展示任务状态指示器和取消/暂停/恢复操作按钮。
       * 为什么这样做：任务控制栏需要始终可见，与 DAG 画布的滚动无关。
       */}
      <TaskControlBar />

      {activePlan ? (
        <>
          {/* ═══ 全局目标固定区域 ═══
           * 做什么：将全局目标信息固定在标题栏下方，不随画布滚动。
           * 为什么这样做：全局目标是用户始终需要参考的核心摘要，
           *               固定后无论画布如何平移/缩放都能快速查看。
           * 视觉约束：与下方画布区域通过边框和背景色明确区分。
           */}
          <div className={`dag-panel-objective-fixed ${objectiveExpanded ? 'expanded' : 'collapsed'}`}>
            {/* 全局目标摘要行 — 始终可见 */}
            <div className="dag-objective-fixed-header">
              <div className="dag-objective-fixed-summary">
                <span className="dag-objective-fixed-label">全局目标</span>
                <span className="dag-objective-fixed-goal">
                  {activePlan.globalObjective.overallGoal || activePlan.planningReason || '（目标待生成）'}
                </span>
              </div>
              <button
                className={`dag-objective-toggle-btn ${objectiveExpanded ? 'expanded' : ''}`}
                onClick={toggleObjective}
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

            {/* 全局目标详情 — 可收起/展开 */}
            <div className="dag-objective-fixed-details">
              <DagGlobalInfoBar />
            </div>
          </div>

          {/* ═══ 画布区域 ═══
           * 做什么：承载可交互、可滑动的节点画布。
           * 为什么这样做：画布区域独立于全局目标固定区域，支持缩放和平移。
           */}
          <div className="dag-panel-canvas-section">
            <DagSearchBar />
            <DagCanvas>
              {activePlan.states.map((state, index) => (
                <React.Fragment key={state.stateId}>
                  {index > 0 && <DagConnections fromState={activePlan.states[index - 1]} toState={state} />}
                  <DagStateGroup state={state} />
                </React.Fragment>
              ))}
            </DagCanvas>
          </div>
        </>
      ) : (
        /* 空状态 */
        <div className="dag-panel-empty-state">
          <DagIconTarget className="dag-panel-empty-icon" />
          <span>等待 Plan 创建...</span>
          <span style={{ fontSize: '11px', color: 'rgba(255, 255, 255, 0.2)' }}>
            切换到智能规划模式并发送消息以启动 DAG 工作流
          </span>
        </div>
      )}
    </div>
  );
};
