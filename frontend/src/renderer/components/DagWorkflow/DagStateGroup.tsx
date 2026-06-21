/**
 * DagStateGroup — State 可视化分组容器。
 * 做什么：将同一 State 内的所有 Step 和 Node 聚合到统一的视觉背景容器中，
 *         展示 State 的目标描述、完成条件、当前状态和耗时。
 * 为什么这样做：State 是 Plan-State-Node 的核心中间层，
 *               前端需要以可视化容器呈现每个 State 的边界。
 * 输入输出：数据来源为 DagPlanProjection.states 中的单个 DagStateProjection。
 * 边界条件：State 内 Step 列表可能为空（尚未生成 Step Plan）。
 * 异常行为：无。
 */
import React, { useEffect, useState } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { DAG_NODE_STATUS_LABEL } from '../../../shared/enum';
import type { DagStateProjection } from '../../types/dagWorkflow';
import { DagStepNode } from './DagStepNode';
import {
  DagIconTarget,
  DagIconCheckCircle,
  DagIconChevronDown,
  DagIconChevronRight,
  DagIconLoader,
  DagIconCheck,
  DagIconAlertTriangle,
  DagIconCircle,
} from './DagIcons';
import './DagStateGroup.css';

/**
 * State 分组容器组件属性。
 */
interface DagStateGroupProps {
  /** State 投影数据 */
  state: DagStateProjection;
}

/**
 * 格式化耗时显示。
 * 做什么：将毫秒数格式化为人类可读的耗时字符串。
 * 规则：< 1s 显示毫秒，>= 1s 显示秒（保留一位小数）。
 */
function formatLatency(ms?: number): string {
  if (ms === undefined || ms === null) return '';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * 根据状态返回对应的图标组件。
 */
function getStatusIcon(status: string): React.FC<React.SVGProps<SVGSVGElement>> {
  switch (status) {
    case 'RUNNING':
      return DagIconLoader;
    case 'SUCCEEDED':
      return DagIconCheck;
    case 'DEGRADED':
      return DagIconCheck;
    case 'FAILED':
      return DagIconAlertTriangle;
    case 'SKIPPED':
      return DagIconCircle;
    default:
      return DagIconCircle;
  }
}

/**
 * State 分组容器组件。
 */
export const DagStateGroup: React.FC<DagStateGroupProps> = ({ state }) => {
  const expandedStates = useDagWorkflowStore((s) => s.expandedStates);
  const toggleStateExpanded = useDagWorkflowStore((s) => s.toggleStateExpanded);
  const searchQuery = useDagWorkflowStore((s) => s.searchQuery);

  const isExpanded = expandedStates[state.stateId] ?? false;

  // 实时耗时计时器
  const [elapsedMs, setElapsedMs] = useState<number | undefined>(state.latencyMs);

  useEffect(() => {
    // 如果 State 正在运行且未结束，启动计时器
    if (state.status === 'RUNNING' && state.startedAtMs && !state.endedAtMs) {
      const timer = setInterval(() => {
        setElapsedMs(Date.now() - state.startedAtMs!);
      }, 100);
      return () => clearInterval(timer);
    } else if (state.latencyMs) {
      setElapsedMs(state.latencyMs);
    } else if (state.endedAtMs && state.startedAtMs) {
      setElapsedMs(state.endedAtMs - state.startedAtMs);
    }
  }, [state.status, state.startedAtMs, state.endedAtMs, state.latencyMs]);

  const StatusIcon = getStatusIcon(state.status);
  const statusLabel = DAG_NODE_STATUS_LABEL[state.status as keyof typeof DAG_NODE_STATUS_LABEL] || state.status;

  // 搜索高亮
  const isSearchMatch = searchQuery.trim().length > 0 && (
    state.goal.toLowerCase().includes(searchQuery.toLowerCase()) ||
    state.intent.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div
      className={`dag-state-group status-${state.status.toLowerCase()} ${isSearchMatch ? 'search-match' : ''}`}
    >
      {/* State 头部 */}
      <div
        className="dag-state-header"
        onClick={() => toggleStateExpanded(state.stateId)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleStateExpanded(state.stateId); }}
      >
        {/* 展开/折叠图标 */}
        <span className="dag-state-toggle-icon">
          {isExpanded ? <DagIconChevronDown width="14" height="14" /> : <DagIconChevronRight width="14" height="14" />}
        </span>

        {/* State 编号和意图 */}
        <span className="dag-state-index">State {state.orderIndex}</span>
        <span className="dag-state-intent">{state.intent}</span>

        {/* 状态和耗时 */}
        <span className="dag-state-status">
          <StatusIcon width="12" height="12" className={`dag-state-status-icon status-icon-${state.status.toLowerCase()}`} />
          <span className="dag-state-status-text">{statusLabel}</span>
          {elapsedMs !== undefined && (
            <span className="dag-state-latency">{formatLatency(elapsedMs)}</span>
          )}
        </span>
      </div>

      {/* State 内容（展开时显示） */}
      {isExpanded && (
        <div className="dag-state-content">
          {/* 目标 */}
          <div className="dag-state-goal">
            <DagIconTarget width="12" height="12" className="dag-state-goal-icon" />
            <span className="dag-state-goal-label">目标</span>
            <span className="dag-state-goal-text">{state.goal}</span>
          </div>

          {/* 完成条件 */}
          {state.completionCriteria.length > 0 && (
            <div className="dag-state-criteria">
              <DagIconCheckCircle width="12" height="12" className="dag-state-criteria-icon" />
              <span className="dag-state-criteria-label">完成条件</span>
              <ul className="dag-state-criteria-list">
                {state.completionCriteria.map((c, i) => (
                  <li key={i}>
                    {c.field} {c.operator} {String(c.value)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Skill 标签 */}
          {state.selectedSkills.length > 0 && (
            <div className="dag-state-skills">
              <span className="dag-state-skills-label">已选 Skills</span>
              <div className="dag-state-skill-tags">
                {state.selectedSkills.map((skill) => (
                  <span key={skill.skillName} className="dag-state-skill-tag" title={skill.description}>
                    {skill.skillName}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Step 列表 */}
          {state.steps.length > 0 && (
            <div className="dag-state-steps">
              {state.steps.map((step) => (
                <DagStepNode key={step.stepId} step={step} />
              ))}
            </div>
          )}

          {/* 评估结果 */}
          {state.evaluationResult && (
            <div className={`dag-state-evaluation ${state.evaluationResult.stateSatisfied ? 'eval-passed' : 'eval-failed'}`}>
              <span className="dag-eval-badge">
                {state.evaluationResult.stateSatisfied ? '通过' : '未通过'}
              </span>
              <span className="dag-eval-reason">{state.evaluationResult.evaluationReason}</span>
              {state.evaluationResult.gapAnalysis && (
                <span className="dag-eval-gap">差距：{state.evaluationResult.gapAnalysis}</span>
              )}
            </div>
          )}

          {/* 错误信息 */}
          {state.errorMessages.length > 0 && (
            <div className="dag-state-errors">
              {state.errorMessages.map((err, i) => (
                <div key={i} className="dag-state-error-item">
                  <DagIconAlertTriangle width="12" height="12" />
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
