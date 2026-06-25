/**
 * AgentFinalVerifyCard — 最终验收卡片组件。
 *
 * 做什么：展示最终验收结果，包括验收报告、逐条条件检查和执行统计。
 * 为什么这样做：Agent Loop 的最终验收是独立的 FinalVerifyNode，与 Plan-State-Node 的汇总不同。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.finalVerification。
 * 边界条件：criteriaVerification 可能为空数组，report 可能为空字符串。
 * 异常行为：无。
 */
import React from 'react';
import type { AgentFinalVerification } from '../../types/agentLoopWorkflow';
import { IconReport, IconCheck, IconXCircle, IconWarning, IconStats } from './icons';

interface AgentFinalVerifyCardProps {
  /** 最终验收投影 */
  verification: AgentFinalVerification;
  /** 总步骤数 */
  totalSteps: number;
  /** 成功步骤数（从 plan 中统计） */
  succeededSteps: number;
  /** 失败步骤数 */
  failedSteps: number;
  /** 总耗时（毫秒） */
  elapsedMs?: number;
  /** 计划版本数 */
  planVersion: number;
}

/** 格式化毫秒为人类可读文本 */
function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

/**
 * 验收状态配置映射。
 * 做什么：根据验收状态返回对应的图标和颜色。
 */
const STATUS_CONFIG: Record<string, { Icon: React.FC<React.SVGProps<SVGSVGElement>>; color: string; label: string }> = {
  completed: { Icon: IconCheck, color: '#22c55e', label: '验收通过' },
  completed_with_gaps: { Icon: IconWarning, color: '#f59e0b', label: '部分标准未满足' },
  failed: { Icon: IconXCircle, color: '#ef4444', label: '验收失败' },
};

/**
 * 最终验收卡片。
 * 做什么：渲染验收报告、逐条条件检查和执行统计。
 * 视觉设计：顶部显示验收状态图标，中间为报告和条件检查，底部为统计信息。
 */
export const AgentFinalVerifyCard: React.FC<AgentFinalVerifyCardProps> = ({
  verification,
  totalSteps,
  succeededSteps,
  failedSteps,
  elapsedMs,
  planVersion,
}) => {
  const config = STATUS_CONFIG[verification.status] || STATUS_CONFIG.failed;
  const { Icon: StatusIcon, color: statusColor, label: statusLabel } = config;

  return (
    <div className="al-final-section">
      {/* 验收头部 */}
      <div className="al-final-header">
        <span className="al-final-icon" style={{ color: statusColor }}>
          <StatusIcon width="20" height="20" />
        </span>
        <span className="al-final-title">{statusLabel}</span>
        <span className="al-final-status">{verification.status}</span>
      </div>

      {/* 验收报告 */}
      {verification.report && (
        <div className="al-final-report">
          <div className="al-final-report-header">
            <IconReport width="14" height="14" />
            <span>报告</span>
          </div>
          <div className="al-final-report-text">{verification.report}</div>
        </div>
      )}

      {/* 逐条条件检查 */}
      {verification.criteriaVerification.length > 0 && (
        <div className="al-final-criteria">
          <div className="al-final-criteria-header">
            <IconCheck width="14" height="14" />
            <span>条件检查 ({verification.criteriaVerification.length})</span>
          </div>
          {verification.criteriaVerification.map((c, i) => (
            <div key={i} className="al-final-criterion">
              <span className="al-final-criterion-icon">
                {c.met ? (
                  <IconCheck width="12" height="12" style={{ color: '#22c55e' }} />
                ) : (
                  <IconXCircle width="12" height="12" style={{ color: '#ef4444' }} />
                )}
              </span>
              <span className="al-final-criterion-text">{c.criterion}</span>
              {c.evidence && (
                <span className="al-final-criterion-evidence">{c.evidence}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 执行统计 */}
      <div className="al-final-stats">
        <div className="al-final-stats-header">
          <IconStats width="14" height="14" />
          <span>执行统计</span>
        </div>
        <div className="al-final-stats-grid">
          <div className="al-final-stat">
            <span className="al-final-stat-value">{totalSteps}</span>
            <span className="al-final-stat-label">总步骤</span>
          </div>
          <div className="al-final-stat">
            <span className="al-final-stat-value" style={{ color: '#22c55e' }}>{succeededSteps}</span>
            <span className="al-final-stat-label">成功</span>
          </div>
          <div className="al-final-stat">
            <span className="al-final-stat-value" style={{ color: '#ef4444' }}>{failedSteps}</span>
            <span className="al-final-stat-label">失败</span>
          </div>
          {elapsedMs !== undefined && (
            <div className="al-final-stat">
              <span className="al-final-stat-value">{formatMs(elapsedMs)}</span>
              <span className="al-final-stat-label">耗时</span>
            </div>
          )}
          <div className="al-final-stat">
            <span className="al-final-stat-value">v{planVersion}</span>
            <span className="al-final-stat-label">计划版本</span>
          </div>
        </div>
      </div>
    </div>
  );
};
