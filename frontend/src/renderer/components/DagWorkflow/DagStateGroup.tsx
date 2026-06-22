/**
 * DagStateGroup — State 可视化子图背景容器。
 * 做什么：将 State 渲染为一个独立的子图背景容器（而非可折叠卡片），
 *         容器头部始终展示 State 的目标描述和完成条件，
 *         容器内部包含该 State 下的所有 Step 可视化节点。
 * 为什么这样做：设计文档要求 State 作为 Plan-State-Node 的核心中间层，
 *               必须以可视化容器形式呈现每个 State 的边界，
 *               让用户在同一视图中区分不同的 State 并理解其目标。
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
  DagIconLoader,
  DagIconCheck,
  DagIconAlertTriangle,
  DagIconCircle,
  DagIconSearch,
  DagIconBarChart,
} from './DagIcons';
import './DagStateGroup.css';

/**
 * State 子图容器组件属性。
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
 * State 子图背景容器组件。
 * 做什么：将 State 渲染为一个独立的子图背景容器，
 *         头部始终展示 State 编号、意图、状态和耗时，
 *         信息区始终展示目标描述和完成条件，
 *         内容区渲染该 State 下的所有 Step 节点。
 * 为什么这样做：State 是 DAG 的核心中间层，必须以背景容器形式呈现其边界，
 *               让用户在同一视图中区分不同 State 并理解各 State 的目标与进展。
 */
export const DagStateGroup: React.FC<DagStateGroupProps> = ({ state }) => {
  const searchQuery = useDagWorkflowStore((s) => s.searchQuery);

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
      {/* ─── State 子图头部（始终可见） ─── */}
      <div className="dag-state-header">
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

      {/* ─── State 信息区：目标 + 完成条件（始终可见，作为子图的描述装饰） ─── */}
      <div className="dag-state-info-area">
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
      </div>

      {/* ─── 分隔线 ─── */}
      <div className="dag-state-divider" />

      {/* ─── State 子图内容区：前置操作 + Step 列表 + 后置操作 ─── */}
      <div className="dag-state-content">
        {/* ─── 前置操作行：Skill 扫描与初筛 ─── */}
        {state.status !== 'PENDING' && (
          <div className="dag-state-ops">
            {/* Skill 扫描 — State 进入 RUNNING 后即展示 */}
            <div className={`dag-state-op-row ${state.steps.length > 0 || state.selectedSkills.length > 0 ? 'op-done' : 'op-running'}`}>
              <DagIconSearch width="11" height="11" className="dag-state-op-icon" />
              <span className="dag-state-op-label">Skill 扫描</span>
              <span className="dag-state-op-status">
                {state.steps.length > 0 || state.selectedSkills.length > 0
                  ? <DagIconCheck width="10" height="10" className="dag-state-op-check" />
                  : <DagIconLoader width="10" height="10" className="dag-state-op-spinner" />
                }
              </span>
            </div>

            {/* Skill 初筛 — selectedSkills 填充后即展示完成 */}
            <div className={`dag-state-op-row ${state.selectedSkills.length > 0 ? 'op-done' : (state.status === 'RUNNING' ? 'op-running' : 'op-pending')}`}>
              <DagIconTarget width="11" height="11" className="dag-state-op-icon" />
              <span className="dag-state-op-label">
                Skill 初筛{state.selectedSkills.length > 0 ? `（${state.selectedSkills.length} 个）` : ''}
              </span>
              <span className="dag-state-op-status">
                {state.selectedSkills.length > 0
                  ? <DagIconCheck width="10" height="10" className="dag-state-op-check" />
                  : (state.status === 'RUNNING'
                    ? <DagIconLoader width="10" height="10" className="dag-state-op-spinner" />
                    : <DagIconCircle width="10" height="10" className="dag-state-op-pending" />
                  )
                }
              </span>
            </div>

            {/* Step 计划生成 — steps 填充后即展示完成 */}
            <div className={`dag-state-op-row ${state.steps.length > 0 ? 'op-done' : (state.selectedSkills.length > 0 ? 'op-running' : 'op-pending')}`}>
              <DagIconBarChart width="11" height="11" className="dag-state-op-icon" />
              <span className="dag-state-op-label">
                Step 计划生成{state.steps.length > 0 ? `（${state.steps.length} 步）` : ''}
              </span>
              <span className="dag-state-op-status">
                {state.steps.length > 0
                  ? <DagIconCheck width="10" height="10" className="dag-state-op-check" />
                  : (state.selectedSkills.length > 0
                    ? <DagIconLoader width="10" height="10" className="dag-state-op-spinner" />
                    : <DagIconCircle width="10" height="10" className="dag-state-op-pending" />
                  )
                }
              </span>
            </div>
          </div>
        )}

        {/* ─── Step 列表（始终渲染） ─── */}
        {state.steps.length > 0 ? (
          <div className="dag-state-steps">
            {state.steps.map((step) => (
              <DagStepNode key={step.stepId} step={step} />
            ))}
          </div>
        ) : (
          state.status !== 'PENDING' && (
            /* Step 尚未生成时的占位提示 */
            <div className="dag-state-steps-empty">
              <span>等待 Step 计划生成...</span>
            </div>
          )
        )}

        {/* ─── 后置操作行：State 评估 ─── */}
        {state.evaluationResult && (
          <div className={`dag-state-evaluation ${state.evaluationResult.stateSatisfied ? 'eval-passed' : 'eval-failed'}`}>
            <DagIconCheckCircle width="11" height="11" className="dag-state-eval-icon" />
            <span className="dag-state-eval-label">State 评估</span>
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
    </div>
  );
};
