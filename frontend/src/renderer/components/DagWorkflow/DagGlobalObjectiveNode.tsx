/**
 * DagGlobalObjectiveNode — 全局目标作为流程图顶部节点。
 * 做什么：将 Plan 的全局目标、实现标准和进度包装为 holographic-node-container 节点，
 *         使其能被 HolographicConnections 自动检测并绘制连线。
 * 为什么这样做：全局目标需要作为流程图的第一个节点，显示在最上方。
 * 输入输出：数据来源为 DagPlanProjection。
 * 边界条件：activePlan 为 null 时不渲染。
 * 异常行为：无。
 */
import React from 'react';
import { DAG_PLAN_STATUS_LABEL } from '../../types/dagWorkflow';
import type { DagPlanProjection } from '../../types/dagWorkflow';
import { DagIconTarget, DagIconCheckCircle, DagIconBarChart, DagIconFileText } from './DagIcons';
import './DagGlobalObjectiveNode.css';

/**
 * 全局目标节点组件属性。
 */
interface DagGlobalObjectiveNodeProps {
  /** Plan 投影数据 */
  plan: DagPlanProjection;
}

/**
 * 全局目标流程图节点组件。
 * 做什么：将全局目标、实现标准、进度和预算渲染为 holographic-node-container 节点。
 * 为什么这样做：作为流程图的起始信息节点，连接后续的 State 节点。
 */
export const DagGlobalObjectiveNode: React.FC<DagGlobalObjectiveNodeProps> = ({ plan }) => {
  const { globalObjective, status, totalStates, completedStates, failedStates, budgetConsumed, budgetLimit } = plan;

  // 计算 State 进度百分比
  const stateProgress = totalStates > 0 ? Math.round((completedStates / totalStates) * 100) : 0;

  // 计算预算消耗百分比
  const budgetMax = budgetLimit.max_total_tool_calls || 50;
  const budgetUsed = budgetConsumed.tool_calls || 0;
  const budgetPercent = budgetMax > 0 ? Math.round((budgetUsed / budgetMax) * 100) : 0;

  // 映射状态
  let visualStatus = 'pending';
  if (status === 'executing') visualStatus = 'running';
  else if (status === 'completed') visualStatus = 'success';
  else if (status === 'terminated' || status === 'budget_exhausted') visualStatus = 'failed';
  else if (status === 'replanning') visualStatus = 'running';

  const statusLabel = DAG_PLAN_STATUS_LABEL[status] || status;

  return (
    <div
      className={`holographic-node-container node-type-dag-objective status-${visualStatus}`}
      data-node-type="dag_global_objective"
    >
      <div className="dag-objective-card">
        <div className="dag-objective-glass" />

        <div className="dag-objective-content">
          {/* 头部：标题 + 状态 */}
          <div className="dag-objective-header">
            <DagIconTarget width="12" height="12" className="dag-objective-icon" />
            <span className="dag-objective-title">全局目标</span>
            <span className={`dag-objective-status status-${status.replace(/_/g, '-')}`}>
              {statusLabel}
            </span>
          </div>

          {/* 目标内容 — 当 overallGoal 为空时回退到 planningReason */}
          <div className="dag-objective-goal" onMouseDown={(e) => e.stopPropagation()}>
            {globalObjective.overallGoal || plan.planningReason || '（目标待生成）'}
          </div>

          {/* 实现标准 — 仅在有值时渲染 */}
          {globalObjective.successCriteria && (
            <div className="dag-objective-criteria">
              <DagIconCheckCircle width="10" height="10" />
              <span className="dag-objective-criteria-label">标准</span>
              <span className="dag-objective-criteria-text" onMouseDown={(e) => e.stopPropagation()}>{globalObjective.successCriteria}</span>
            </div>
          )}

          {/* 输出格式（仅在有值时渲染） */}
          {globalObjective.outputFormat && (
            <div className="dag-objective-format">
              <DagIconFileText width="10" height="10" />
              <span className="dag-objective-format-label">格式</span>
              <span className="dag-objective-format-text" onMouseDown={(e) => e.stopPropagation()}>{globalObjective.outputFormat}</span>
            </div>
          )}

          {/* 进度和预算 */}
          <div className="dag-objective-stats">
            <div className="dag-objective-stat">
              <DagIconBarChart width="10" height="10" />
              <span className="dag-objective-stat-label">进度</span>
              <div className="dag-objective-progress-track">
                <div className="dag-objective-progress-fill" style={{ width: `${stateProgress}%` }} />
              </div>
              <span className="dag-objective-stat-value">{completedStates}/{totalStates}</span>
            </div>
            <div className="dag-objective-stat">
              <span className="dag-objective-stat-label">预算</span>
              <div className="dag-objective-progress-track">
                <div
                  className={`dag-objective-progress-fill ${budgetPercent >= 80 ? 'budget-critical' : budgetPercent >= 60 ? 'budget-warning' : ''}`}
                  style={{ width: `${Math.min(budgetPercent, 100)}%` }}
                />
              </div>
              <span className="dag-objective-stat-value">{budgetUsed}/{budgetMax}</span>
            </div>
          </div>

          {/* 约束条件（仅在有值时渲染） */}
          {globalObjective.constraints && globalObjective.constraints.length > 0 && (
            <div className="dag-objective-constraints">
              <span className="dag-objective-constraints-label">约束 ({globalObjective.constraints.length})</span>
              <ul className="dag-objective-constraints-list">
                {globalObjective.constraints.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
