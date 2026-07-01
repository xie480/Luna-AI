/**
 * DagStepNode — Step 可视化节点。
 * 做什么：展示 Step 描述和执行模式（并行/串行），包含该 Step 下的所有原子节点卡片。
 * 为什么这样做：Step 是 State 内部的执行分组，需要区分并行/串行渲染模式。
 * 输入输出：数据来源为 DagStateProjection.steps 中的单个 DagStepProjection。
 * 边界条件：Step 内 Node 列表可能为空。
 * 异常行为：无。
 */
import React, { useEffect, useState } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { DAG_NODE_STATUS_LABEL } from '../../../shared/enum';
import type { DagStepProjection } from '../../types/dagWorkflow';
import { DagAtomicNode } from './DagAtomicNode';
import {
  DagIconZap,
  DagIconArrowRight,
  DagIconChevronDown,
  DagIconChevronRight,
  DagIconLoader,
  DagIconCheck,
  DagIconAlertTriangle,
  DagIconCircle,
} from './DagIcons';
import './DagStepNode.css';

/**
 * Step 节点组件属性。
 */
interface DagStepNodeProps {
  /** Step 投影数据 */
  step: DagStepProjection;
  /** ★ Phase 10 新增：是否从此 Step 恢复执行 */
  isRecoveryPoint?: boolean;
  /** ★ Phase 10 新增：恢复标记文案 */
  recoveryLabel?: string;
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
    default:
      return DagIconCircle;
  }
}

/**
 * Step 可视化节点组件。
 */
import { DagIconRefresh } from './DagIcons';

export const DagStepNode: React.FC<DagStepNodeProps> = ({
  step,
  isRecoveryPoint = false,
  recoveryLabel = '从断点恢复',
}) => {
  const expandedSteps = useDagWorkflowStore((s) => s.expandedSteps);
  const toggleStepExpanded = useDagWorkflowStore((s) => s.toggleStepExpanded);
  const searchQuery = useDagWorkflowStore((s) => s.searchQuery);

  const isExpanded = expandedSteps[step.stepId] ?? true;

  // 实时耗时计时器
  const [elapsedMs, setElapsedMs] = useState<number | undefined>(step.latencyMs);

  useEffect(() => {
    if (step.status === 'RUNNING' && step.startedAtMs && !step.endedAtMs) {
      const timer = setInterval(() => {
        setElapsedMs(Date.now() - step.startedAtMs!);
      }, 100);
      return () => clearInterval(timer);
    } else if (step.latencyMs) {
      setElapsedMs(step.latencyMs);
    } else if (step.endedAtMs && step.startedAtMs) {
      setElapsedMs(step.endedAtMs - step.startedAtMs);
    }
  }, [step.status, step.startedAtMs, step.endedAtMs, step.latencyMs]);

  const StatusIcon = getStatusIcon(step.status);
  const statusLabel = DAG_NODE_STATUS_LABEL[step.status as keyof typeof DAG_NODE_STATUS_LABEL] || step.status;
  const isParallel = step.executionMode === 'parallel';

  // 搜索高亮
  const isSearchMatch = searchQuery.trim().length > 0 && (
    step.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className={`dag-step-node status-${step.status.toLowerCase()} ${isSearchMatch ? 'search-match' : ''} ${isRecoveryPoint ? 'recovery-point' : ''}`}>
      {/* Phase 10 恢复点标记 */}
      {isRecoveryPoint && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '3px 8px', fontSize: '10px',
          color: '#7c4dff', fontFamily: "'Courier New', monospace",
          background: 'rgba(124, 77, 255, 0.08)',
          borderBottom: '1px solid rgba(124, 77, 255, 0.15)',
        }}>
          <DagIconRefresh width="10" height="10" />
          {recoveryLabel}
        </div>
      )}
      {/* Step 头部 */}
      <div
        className="dag-step-header"
        onClick={() => toggleStepExpanded(step.stepId)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleStepExpanded(step.stepId); }}
      >
        <span className="dag-step-toggle-icon">
          {isExpanded ? <DagIconChevronDown width="12" height="12" /> : <DagIconChevronRight width="12" height="12" />}
        </span>

        <span className="dag-step-index">Step {step.stepIndex}</span>
        <span className="dag-step-desc" title={step.description}>{step.description}</span>

        {/* 执行模式标签 */}
        <span className={`dag-step-mode-badge ${isParallel ? 'mode-parallel' : 'mode-serial'}`}>
          {isParallel ? <DagIconZap width="10" height="10" /> : <DagIconArrowRight width="10" height="10" />}
          {isParallel ? '并行' : '串行'}
        </span>

        {/* 状态和耗时 */}
        <span className="dag-step-status">
          <StatusIcon width="11" height="11" className={`dag-step-status-icon status-icon-${step.status.toLowerCase()}`} />
          <span className="dag-step-status-text">{statusLabel}</span>
          {elapsedMs !== undefined && (
            <span className="dag-step-latency">{formatLatency(elapsedMs)}</span>
          )}
        </span>
      </div>

      {/* Step 内容（展开时显示） */}
      {isExpanded && step.nodes.length > 0 && (
        <div className={`dag-step-content ${isParallel ? 'content-parallel' : 'content-serial'}`}>
          {step.nodes.map((node) => (
            <DagAtomicNode key={node.nodeId} node={node} />
          ))}
        </div>
      )}
    </div>
  );
};
