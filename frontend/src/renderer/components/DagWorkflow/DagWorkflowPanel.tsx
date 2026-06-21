/**
 * DagWorkflowPanel — DAG 深度工作流主面板。
 * 做什么：作为 DAG 可视化的顶层容器，组合全局信息栏、画布和搜索栏。
 * 为什么这样做：Plan-State-Node 模式需要独立的面板来承载四层嵌套的可视化结构。
 * 输入输出：数据来源为 dagWorkflowStore.activePlan，仅在 plan_state_node 模式下渲染。
 * 边界条件：activePlan 为 null 时展示空状态提示。
 * 异常行为：无。
 */
import React from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { DagGlobalInfoBar } from './DagGlobalInfoBar';
import { DagCanvas } from './DagCanvas';
import { DagStateGroup } from './DagStateGroup';
import { DagConnections } from './DagConnections';
import { DagSearchBar } from './DagSearchBar';
import { DagIconX, DagIconTarget } from './DagIcons';
import './DagWorkflowPanel.css';

/**
 * DAG 工作流主面板组件。
 */
export const DagWorkflowPanel: React.FC = () => {
  const activePlan = useDagWorkflowStore((state) => state.activePlan);
  const clearPlan = useDagWorkflowStore((state) => state.clearPlan);

  return (
    <div className="dag-workflow-panel">
      {/* 顶部工具栏 */}
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

      {activePlan ? (
        <>
          {/* 全局信息栏 */}
          <div className="dag-panel-info-section">
            <DagGlobalInfoBar />
          </div>

          {/* 画布区域 */}
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
