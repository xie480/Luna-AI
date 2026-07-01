/**
 * DagGlobalInfoBar — 全局 Plan 信息栏。
 * 做什么：展示 DAG Plan 的全局目标、成功标准、整体进度和预算消耗。
 * 为什么这样做：用户需要在 DAG 面板顶部快速了解当前 Plan 的整体状态。
 * 输入输出：数据来源为 dagWorkflowStore.activePlan。
 * 边界条件：activePlan 为 null 时不渲染。
 * 异常行为：无。
 */
import React, { useState } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { useTaskStateStore } from '../../stores/taskStateStore';
import { DAG_PLAN_STATUS_LABEL } from '../../types/dagWorkflow';
import { DagIconRefresh } from './DagIcons';
import { DagIconTarget, DagIconCheckCircle, DagIconBarChart, DagIconWrench, DagIconFileText, DagIconChevronRight, DagIconChevronDown } from './DagIcons';
import './DagGlobalInfoBar.css';

/**
 * 全局信息栏组件。
 */
export const DagGlobalInfoBar: React.FC = () => {
  const activePlan = useDagWorkflowStore((state) => state.activePlan);
  const [constraintsExpanded, setConstraintsExpanded] = useState(false);

  if (!activePlan) return null;

  const { globalObjective, status, totalStates, completedStates, failedStates, budgetConsumed, budgetLimit } = activePlan;

  // 计算 State 进度百分比
  const stateProgress = totalStates > 0 ? Math.round((completedStates / totalStates) * 100) : 0;

  // 计算预算消耗百分比
  const budgetMax = budgetLimit.max_total_tool_calls || 50;
  const budgetUsed = budgetConsumed.tool_calls || 0;
  const budgetPercent = budgetMax > 0 ? Math.round((budgetUsed / budgetMax) * 100) : 0;

  // 预算进度条样式
  let budgetFillClass = 'dag-progress-fill';
  if (budgetPercent >= 80) {
    budgetFillClass += ' budget-critical';
  } else if (budgetPercent >= 60) {
    budgetFillClass += ' budget-warning';
  }

  // 状态标签
  const statusLabel = DAG_PLAN_STATUS_LABEL[status] || status;

  return (
    <div className="dag-global-info-bar">
      {/* 全局目标行 */}
      <div className="dag-info-row">
        <DagIconTarget className="dag-info-row-icon" />
        <span className="dag-info-row-label">目标</span>
        <span className="dag-info-row-content">{globalObjective.overallGoal}</span>
        <span className={`dag-plan-status-badge status-${status.replace(/_/g, '-')}`}>
          {statusLabel}
        </span>
      </div>

      {/* 实现标准行 */}
      <div className="dag-info-row">
        <DagIconCheckCircle className="dag-info-row-icon" />
        <span className="dag-info-row-label">标准</span>
        <span className="dag-info-row-content">{globalObjective.successCriteria}</span>
      </div>

      {/* 输出格式行（仅在有值时渲染） */}
      {globalObjective.outputFormat && (
        <div className="dag-info-row">
          <DagIconFileText className="dag-info-row-icon" />
          <span className="dag-info-row-label">格式</span>
          <span className="dag-info-row-content">{globalObjective.outputFormat}</span>
        </div>
      )}

      {/* State 进度行 */}
      <div className="dag-info-row">
        <DagIconBarChart className="dag-info-row-icon" />
        <span className="dag-info-row-label">进度</span>
        <div className="dag-progress-bar-wrapper">
          <div className="dag-progress-track">
            <div
              className="dag-progress-fill"
              style={{ width: `${stateProgress}%` }}
            />
          </div>
          <span className="dag-progress-text">
            {completedStates}/{totalStates}
            {failedStates > 0 && <span style={{ color: '#ff003c' }}> ({failedStates} 失败)</span>}
          </span>
        </div>
      </div>

      {/* 预算消耗行 */}
      <div className="dag-info-row">
        <DagIconWrench className="dag-info-row-icon" />
        <span className="dag-info-row-label">预算</span>
        <div className="dag-progress-bar-wrapper">
          <div className="dag-progress-track">
            <div
              className={budgetFillClass}
              style={{ width: `${Math.min(budgetPercent, 100)}%` }}
            />
          </div>
          <span className="dag-progress-text">{budgetUsed}/{budgetMax}</span>
        </div>
      </div>

      {/* Phase 10：恢复信息展示 */}
      {useTaskStateStore.getState().recoveryInfo && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '4px 12px', fontSize: '11px',
          color: '#7c4dff',
          background: 'rgba(124, 77, 255, 0.06)',
          borderBottom: '1px solid rgba(124, 77, 255, 0.15)',
        }}>
          <DagIconRefresh width="12" height="12" />
          <span>从断点恢复</span>
          <span style={{ fontFamily: "'Courier New', monospace", opacity: 0.7 }}>
            快照版本: {useTaskStateStore.getState().recoveryInfo?.snapshotVersion}
          </span>
        </div>
      )}

      {/* 约束条件折叠区域 */}
      {globalObjective.constraints && globalObjective.constraints.length > 0 && (
        <div className="dag-constraints-section">
          <button
            className={`dag-constraints-toggle ${constraintsExpanded ? 'expanded' : ''}`}
            onClick={() => setConstraintsExpanded(!constraintsExpanded)}
            type="button"
          >
            {constraintsExpanded ? <DagIconChevronDown /> : <DagIconChevronRight />}
            约束条件 ({globalObjective.constraints.length})
          </button>
          {constraintsExpanded && (
            <ul className="dag-constraints-list">
              {globalObjective.constraints.map((constraint, index) => (
                <li key={index}>{constraint}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
