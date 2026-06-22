/**
 * DagStateNode — State 作为流程图节点。
 * 做什么：将 State 子图容器包装为 holographic-node-container 节点，
 *         使其能被 HolographicConnections 自动检测并绘制连线。
 * 为什么这样做：HolographicConnections 通过查询 .node-list > .holographic-node-container[data-node-type]
 *               来定位 DOM 节点并计算连线路径，State 必须符合这个结构。
 * 输入输出：数据来源为 DagStateProjection。
 * 边界条件：State 内 Step 列表可能为空。
 * 异常行为：无。
 */
import React, { useEffect, useState } from 'react';
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
  DagIconChevronDown,
  DagIconChevronRight,
  DagIconSearch,
} from './DagIcons';
import './DagStateNode.css';

/**
 * State 节点组件属性。
 */
interface DagStateNodeProps {
  /** State 投影数据 */
  state: DagStateProjection;
}

/**
 * 格式化耗时显示。
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
 * State 流程图节点组件。
 * 做什么：将 State 渲染为 holographic-node-container 节点，
 *         内部展示目标、完成条件和 Step 子图。
 * 为什么这样做：融入 HolographicConnections 连线系统，同时保持 State 子图的语义。
 */
export const DagStateNode: React.FC<DagStateNodeProps> = ({ state }) => {
  const [expanded, setExpanded] = useState(false);
  const StatusIcon = getStatusIcon(state.status);
  const statusLabel = DAG_NODE_STATUS_LABEL[state.status as keyof typeof DAG_NODE_STATUS_LABEL] || state.status;

  // 实时耗时计时器
  const [elapsedMs, setElapsedMs] = useState<number | undefined>(state.latencyMs);

  useEffect(() => {
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

  // 映射状态到 HolographicNode 的视觉状态
  let visualStatus = 'pending';
  if (state.status === 'RUNNING') visualStatus = 'running';
  else if (state.status === 'SUCCEEDED') visualStatus = 'success';
  else if (state.status === 'FAILED') visualStatus = 'failed';
  else if (state.status === 'DEGRADED') visualStatus = 'failed';
  else if (state.status === 'SKIPPED') visualStatus = 'bypassed';

  return (
    <div
      className={`holographic-node-container node-type-dag-state status-${visualStatus}`}
      data-node-type={state.stateId}
    >
      <div className="dag-state-node-card">
        <div className="dag-state-node-glass" />

        <div className="dag-state-node-content">
          {/* 头部：State 编号 + 意图 + 状态 */}
          <div className="dag-state-node-header">
            <span className="dag-state-node-index">State {state.orderIndex}</span>
            <span className="dag-state-node-intent" title={state.intent}>{state.intent}</span>
            <span className="dag-state-node-status">
              <StatusIcon width="11" height="11" />
              <span>{statusLabel}</span>
              {elapsedMs !== undefined && <span className="dag-state-node-latency">{formatLatency(elapsedMs)}</span>}
            </span>
          </div>

          {/* 目标 */}
          <div className="dag-state-node-goal">
            <DagIconTarget width="10" height="10" />
            <span className="dag-state-node-goal-label">目标</span>
            <span className="dag-state-node-goal-text">{state.goal}</span>
          </div>

          {/* 完成条件 */}
          {state.completionCriteria.length > 0 && (
            <div className="dag-state-node-criteria">
              <DagIconCheckCircle width="10" height="10" />
              <span className="dag-state-node-criteria-label">完成条件</span>
              <ul className="dag-state-node-criteria-list">
                {state.completionCriteria.map((c, i) => (
                  <li key={i}>{c.field} {c.operator} {String(c.value)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Skill 标签 */}
          {state.selectedSkills.length > 0 && (
            <div className="dag-state-node-skills">
              {state.selectedSkills.map((skill) => (
                <span key={skill.skillName} className="dag-state-node-skill-tag" title={skill.description}>
                  {skill.skillName}
                </span>
              ))}
            </div>
          )}

          {/* ─── 前置操作行：Skill 扫描与初筛 ─── */}
          {state.status !== 'PENDING' && (
            <div className="dag-state-node-ops">
              {/* Skill 扫描 */}
              <div className={`dag-state-node-op-row ${state.steps.length > 0 || state.selectedSkills.length > 0 ? 'op-done' : 'op-running'}`}>
                <DagIconSearch width="9" height="9" className="dag-state-node-op-icon" />
                <span className="dag-state-node-op-label">Skill 扫描</span>
                <span className="dag-state-node-op-status">
                  {state.steps.length > 0 || state.selectedSkills.length > 0
                    ? <DagIconCheck width="9" height="9" className="dag-state-node-op-check" />
                    : <DagIconLoader width="9" height="9" className="dag-state-node-op-spinner" />
                  }
                </span>
              </div>

              {/* Skill 初筛 */}
              <div className={`dag-state-node-op-row ${state.selectedSkills.length > 0 ? 'op-done' : (state.status === 'RUNNING' ? 'op-running' : 'op-pending')}`}>
                <DagIconTarget width="9" height="9" className="dag-state-node-op-icon" />
                <span className="dag-state-node-op-label">
                  Skill 初筛{state.selectedSkills.length > 0 ? `（${state.selectedSkills.length}）` : ''}
                </span>
                <span className="dag-state-node-op-status">
                  {state.selectedSkills.length > 0
                    ? <DagIconCheck width="9" height="9" className="dag-state-node-op-check" />
                    : (state.status === 'RUNNING'
                      ? <DagIconLoader width="9" height="9" className="dag-state-node-op-spinner" />
                      : <DagIconCircle width="9" height="9" className="dag-state-node-op-pending" />
                    )
                  }
                </span>
              </div>

              {/* Step 计划生成 */}
              <div className={`dag-state-node-op-row ${state.steps.length > 0 ? 'op-done' : (state.selectedSkills.length > 0 ? 'op-running' : 'op-pending')}`}>
                <DagIconCheckCircle width="9" height="9" className="dag-state-node-op-icon" />
                <span className="dag-state-node-op-label">
                  Step 计划{state.steps.length > 0 ? `（${state.steps.length} 步）` : ''}
                </span>
                <span className="dag-state-node-op-status">
                  {state.steps.length > 0
                    ? <DagIconCheck width="9" height="9" className="dag-state-node-op-check" />
                    : (state.selectedSkills.length > 0
                      ? <DagIconLoader width="9" height="9" className="dag-state-node-op-spinner" />
                      : <DagIconCircle width="9" height="9" className="dag-state-node-op-pending" />
                    )
                  }
                </span>
              </div>
            </div>
          )}

          {/* Steps 展开/折叠区域 */}
          {state.steps.length > 0 && (
            <div className="dag-state-node-steps-section">
              <button
                className="dag-state-node-steps-toggle"
                onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
                type="button"
              >
                {expanded ? <DagIconChevronDown width="10" height="10" /> : <DagIconChevronRight width="10" height="10" />}
                <span>Steps ({state.steps.length})</span>
              </button>
              {expanded && (
                <div className="dag-state-node-steps-list">
                  {state.steps.map((step) => (
                    <DagStepNode key={step.stepId} step={step} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ─── 后置操作行：State 评估 ─── */}
          {state.evaluationResult && (
            <div className={`dag-state-node-eval ${state.evaluationResult.stateSatisfied ? 'eval-passed' : 'eval-failed'}`}>
              <DagIconCheckCircle width="9" height="9" className="dag-state-node-eval-icon" />
              <span className="dag-state-node-eval-label">State 评估</span>
              <span className="dag-eval-badge">
                {state.evaluationResult.stateSatisfied ? '通过' : '未通过'}
              </span>
              <span>{state.evaluationResult.evaluationReason}</span>
            </div>
          )}

          {/* 错误信息 */}
          {state.errorMessages.length > 0 && (
            <div className="dag-state-node-errors">
              {state.errorMessages.map((err, i) => (
                <div key={i} className="dag-state-node-error-item">
                  <DagIconAlertTriangle width="10" height="10" />
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
