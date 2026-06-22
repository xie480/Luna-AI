/**
 * DagAtomicNode — 原子节点卡片。
 * 做什么：展示单个原子节点的完整状态，包括类型图标、描述、输入输出参数、
 *         耗时计时器、中间日志和错误信息。
 * 为什么这样做：这是 DAG 可视化最细粒度的数据单元，用户需要在此级别查看执行细节。
 * 输入输出：数据来源为 DagStepProjection.nodes 中的单个 DagNodeProjection。
 * 边界条件：inputs/outputs 可能为空对象，intermediateLogs 可能为空数组。
 * 异常行为：无。
 */
import React, { useEffect, useState } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { DAG_NODE_STATUS_LABEL, DAG_NODE_TYPE_LABEL } from '../../../shared/enum';
import type { DagNodeProjection } from '../../types/dagWorkflow';
import {
  getDagNodeIcon,
  getDagNodeColor,
  DagIconLoader,
  DagIconCheck,
  DagIconAlertTriangle,
  DagIconCircle,
  DagIconShield,
  DagIconChevronDown,
  DagIconChevronRight,
} from './DagIcons';
import './DagAtomicNode.css';

/**
 * 原子节点卡片组件属性。
 */
interface DagAtomicNodeProps {
  /** 节点投影数据 */
  node: DagNodeProjection;
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
    case 'PENDING_USER_APPROVAL':
      return DagIconShield;
    default:
      return DagIconCircle;
  }
}

/**
 * 原子节点卡片组件。
 */
export const DagAtomicNode: React.FC<DagAtomicNodeProps> = ({ node }) => {
  const expandedNodes = useDagWorkflowStore((s) => s.expandedNodes);
  const toggleNodeExpanded = useDagWorkflowStore((s) => s.toggleNodeExpanded);
  const searchQuery = useDagWorkflowStore((s) => s.searchQuery);

  const isExpanded = expandedNodes[node.nodeId] ?? false;

  // 实时耗时计时器
  const [elapsedMs, setElapsedMs] = useState<number | undefined>(node.latencyMs);

  useEffect(() => {
    if (node.status === 'RUNNING' && node.startedAtMs && !node.endedAtMs) {
      const timer = setInterval(() => {
        setElapsedMs(Date.now() - node.startedAtMs!);
      }, 100);
      return () => clearInterval(timer);
    } else if (node.latencyMs) {
      setElapsedMs(node.latencyMs);
    } else if (node.endedAtMs && node.startedAtMs) {
      setElapsedMs(node.endedAtMs - node.startedAtMs);
    }
  }, [node.status, node.startedAtMs, node.endedAtMs, node.latencyMs]);

  const NodeIcon = getDagNodeIcon(node.nodeType);
  const nodeColor = getDagNodeColor(node.nodeType);
  const StatusIcon = getStatusIcon(node.status);
  const statusLabel = DAG_NODE_STATUS_LABEL[node.status as keyof typeof DAG_NODE_STATUS_LABEL] || node.status;
  const typeLabel = DAG_NODE_TYPE_LABEL[node.nodeType as keyof typeof DAG_NODE_TYPE_LABEL] || node.nodeType;

  // 搜索高亮
  const isSearchMatch = searchQuery.trim().length > 0 && (
    node.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (node.toolName && node.toolName.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (node.skillName && node.skillName.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (node.resourceName && node.resourceName.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  // 节点描述（优先使用 toolName/skillName/resourceName）
  const nodeDisplayName = node.toolName || node.skillName || node.resourceName || node.description;

  return (
    <div
      className={`dag-atomic-node-card status-${node.status.toLowerCase()} ${isSearchMatch ? 'search-match' : ''}`}
      style={{ '--node-color': nodeColor } as React.CSSProperties}
    >
      {/* 卡片头部 */}
      <div
        className="dag-node-header"
        onClick={() => toggleNodeExpanded(node.nodeId)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleNodeExpanded(node.nodeId); }}
      >
        <span className="dag-node-expand-icon">
          {isExpanded ? <DagIconChevronDown width="10" height="10" /> : <DagIconChevronRight width="10" height="10" />}
        </span>

        <NodeIcon width="14" height="14" className="dag-node-type-icon" />
        <span className="dag-node-type-label">{typeLabel}</span>

        <span className="dag-node-name" title={nodeDisplayName}>{nodeDisplayName}</span>

        <span className="dag-node-status">
          <StatusIcon width="11" height="11" className={`dag-node-status-icon status-icon-${node.status.toLowerCase()}`} />
          <span className="dag-node-status-text">{statusLabel}</span>
          {elapsedMs !== undefined && (
            <span className="dag-node-latency">{formatLatency(elapsedMs)}</span>
          )}
        </span>

        {/* Gating 审批标记 */}
        {node.gatingRequired && (
          <DagIconShield width="12" height="12" className="dag-node-gating-icon" title="需要审批" />
        )}

        {/* 重试标记 */}
        {node.retryCount > 0 && (
          <span className="dag-node-retry-badge">重试 {node.retryCount}/{node.maxRetries}</span>
        )}
      </div>

      {/* 卡片详情（展开时显示） */}
      {isExpanded && (
        <div className="dag-node-details">
          {/* 输入参数 */}
          {Object.keys(node.inputs).length > 0 && (
            <div className="dag-node-params-section">
              <span className="dag-node-params-label">输入参数</span>
              <div className="dag-node-params-list">
                {Object.entries(node.inputs).map(([key, value]) => (
                  <div key={key} className="dag-node-param-item">
                    <span className="dag-node-param-key">{key}:</span>
                    <span className="dag-node-param-value">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 执行结果（输出参数）— 始终展示区域标题，无数据时显示占位提示 */}
          <div className="dag-node-params-section">
            <span className="dag-node-params-label">执行结果</span>
            {Object.keys(node.outputs).length > 0 ? (
              <div className="dag-node-params-list">
                {Object.entries(node.outputs).map(([key, value]) => (
                  <div key={key} className="dag-node-param-item">
                    <span className="dag-node-param-key">{key}:</span>
                    <span className="dag-node-param-value" title={typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}>
                      {typeof value === 'object' ? JSON.stringify(value).slice(0, 200) : String(value).slice(0, 200)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <span className="dag-node-params-empty">
                {node.status === 'RUNNING' ? '执行中...' : node.status === 'PENDING' ? '等待执行' : '无输出数据'}
              </span>
            )}
          </div>

          {/* 中间日志 */}
          {node.intermediateLogs.length > 0 && (
            <div className="dag-node-logs-section">
              <span className="dag-node-logs-label">中间日志 ({node.intermediateLogs.length})</span>
              <div className="dag-node-logs-list">
                {node.intermediateLogs.map((log) => (
                  <div key={log.logId} className={`dag-node-log-item log-${log.level}`}>
                    <span className="dag-node-log-time">
                      {new Date(log.timestampMs).toLocaleTimeString()}
                    </span>
                    <span className="dag-node-log-msg">{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 错误详情（展开时在详情区内展示） */}
          {node.status === 'FAILED' && node.errorMessage && (
            <div className="dag-node-error-detail">
              <DagIconAlertTriangle width="10" height="10" />
              <span className="dag-node-error-detail-text">{node.errorMessage}</span>
            </div>
          )}
        </div>
      )}

      {/* 错误信息条（FAILED 状态时始终显示，不论是否展开） */}
      {node.status === 'FAILED' && node.errorMessage && (
        <div className="dag-node-error-bar">
          <DagIconAlertTriangle width="12" height="12" />
          <span>{node.errorMessage}</span>
        </div>
      )}
    </div>
  );
};
