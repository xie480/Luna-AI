/**
 * AgentStepCard — 单步卡片组件。
 *
 * 做什么：展示单个 Step 的完整执行详情，包括 Think → ToolCalls → Observe → Evaluate 全过程。
 * 为什么这样做：步进式推进是 Agent Loop 的核心交互模式，每一步都需要可展开查看详情。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.plan.steps[i]。
 * 边界条件：所有执行详情字段都可能为空，渲染时必须做空值保护。
 * 异常行为：无。
 */
import React from 'react';
import type { AgentStepProjection, AgentStepStatus } from '../../types/agentLoopWorkflow';
import {
  IconChevron,
  IconThink,
  IconTool,
  IconObserve,
  IconEvaluate,
  IconRetry,
  IconRepair,
  IconCheck,
  IconXCircle,
  IconWarning,
  IconPending,
  IconClock,
} from './icons';

// ============================================================
// 常量映射
// ============================================================

/** 步骤状态颜色映射（与赛博朋克全息流程图对齐） */
const STATUS_COLOR: Record<AgentStepStatus, string> = {
  pending: 'rgba(255, 255, 255, 0.25)',
  running: '#00ffff',
  passed: '#00fa9a',
  failed: '#ff003c',
  skipped: 'rgba(255, 255, 255, 0.15)',
};

/** 步骤状态中文标签 */
const STATUS_LABEL: Record<AgentStepStatus, string> = {
  pending: '等待中',
  running: '执行中',
  passed: '通过',
  failed: '失败',
  skipped: '已跳过',
};

/** 步骤状态图标 */
const StatusIcon: React.FC<{ status: AgentStepStatus }> = ({ status }) => {
  const props = { width: '12', height: '12' };
  switch (status) {
    case 'passed':
      return <IconCheck {...props} style={{ color: STATUS_COLOR.passed }} />;
    case 'failed':
      return <IconXCircle {...props} style={{ color: STATUS_COLOR.failed }} />;
    case 'running':
      return (
        <span className="al-step-pulse">
          <IconPending {...props} style={{ color: STATUS_COLOR.running }} />
        </span>
      );
    case 'skipped':
      return <IconPending {...props} style={{ color: STATUS_COLOR.skipped, opacity: 0.5 }} />;
    default:
      return <IconPending {...props} style={{ color: STATUS_COLOR.pending }} />;
  }
};

/** 评估结论颜色映射（赛博朋克色系） */
const VERDICT_COLOR: Record<string, string> = {
  pass: '#00fa9a',
  fail: '#ff003c',
  partial: '#ffaa00',
  needs_replan: '#ffaa00',
};

/** 评估结论中文标签 */
const VERDICT_LABEL: Record<string, string> = {
  pass: '通过',
  fail: '失败',
  partial: '部分完成',
  needs_replan: '需重规划',
};

// ============================================================
// 工具函数
// ============================================================

/** 格式化毫秒为人类可读文本 */
function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

// ============================================================
// Props
// ============================================================

interface AgentStepCardProps {
  /** 步骤投影 */
  step: AgentStepProjection;
  /** 步骤索引 */
  index: number;
  /** 是否为当前执行步骤 */
  isCurrent: boolean;
  /** 整体展开/折叠状态 */
  isExpanded: boolean;
  /** Think 区块展开状态 */
  isThoughtExpanded: boolean;
  /** Observe 区块展开状态 */
  isObservationExpanded: boolean;
  /** Evaluate 区块展开状态 */
  isEvaluationExpanded: boolean;
  /** 切换整体展开/折叠 */
  onToggle: () => void;
  /** 切换 Think 展开 */
  onToggleThought: () => void;
  /** 切换 Observe 展开 */
  onToggleObservation: () => void;
  /** 切换 Evaluate 展开 */
  onToggleEvaluation: () => void;
}

// ============================================================
// 组件实现
// ============================================================

/**
 * 单步卡片。
 * 做什么：渲染一个可展开的步骤卡片，展示 Think → Tool → Observe → Evaluate 全过程。
 * 视觉设计：当前执行步骤高亮边框，已完成步骤降低透明度。
 */
export const AgentStepCard: React.FC<AgentStepCardProps> = ({
  step,
  index,
  isCurrent,
  isExpanded,
  isThoughtExpanded,
  isObservationExpanded,
  isEvaluationExpanded,
  onToggle,
  onToggleThought,
  onToggleObservation,
  onToggleEvaluation,
}) => {
  /** 是否有可展开的执行详情内容 */
  const hasContent = step.lastThought || step.toolCalls.length > 0 || step.lastObservation || step.evaluationResult;

  return (
    <div
      className={`al-step-card ${isCurrent ? 'al-step-card--current' : ''} ${isExpanded ? 'al-step-card--expanded' : ''}`}
      data-status={step.status}
    >
      {/* 步骤头部 */}
      <button className="al-step-header" onClick={onToggle} type="button">
        <span className="al-step-index">{index + 1}</span>
        <StatusIcon status={step.status} />
        <span className="al-step-title">{step.title || `步骤 ${index + 1}`}</span>
        <span className="al-step-status-text" style={{ color: STATUS_COLOR[step.status] }}>
          {STATUS_LABEL[step.status]}
        </span>
        {step.latencyMs !== undefined && step.latencyMs > 0 && (
          <span className="al-step-time">
            <IconClock width="10" height="10" />
            {formatMs(step.latencyMs)}
          </span>
        )}
        {step.retryCount > 0 && (
          <span className="al-step-badge" title="重试次数">
            <IconRetry width="11" height="11" />
            {step.retryCount}
          </span>
        )}
        {step.repairCount > 0 && (
          <span className="al-step-badge" title="修复次数">
            <IconRepair width="11" height="11" />
            {step.repairCount}
          </span>
        )}
        {hasContent && (
          <span className="al-step-chevron">
            <IconChevron direction={isExpanded ? 'down' : 'right'} width="12" height="12" />
          </span>
        )}
      </button>

      {/* 步骤详情（展开时显示） */}
      {isExpanded && (
        <div className="al-step-details">
          {/* 意图 */}
          {step.intent && (
            <div className="al-step-field">
              <span className="al-step-label">意图</span>
              <span className="al-step-value">{step.intent}</span>
            </div>
          )}
          {/* 预期输出 */}
          {step.expectedOutput && (
            <div className="al-step-field">
              <span className="al-step-label">预期输出</span>
              <span className="al-step-value">{step.expectedOutput}</span>
            </div>
          )}
          {/* 风险提示 */}
          {step.riskNotes && (
            <div className="al-step-field">
              <span className="al-step-label">
                <IconWarning width="10" height="10" /> 风险
              </span>
              <span className="al-step-value">{step.riskNotes}</span>
            </div>
          )}

          {/* ── Think 区块（可折叠）── */}
          {step.lastThought && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleThought} type="button">
                <IconChevron direction={isThoughtExpanded ? 'down' : 'right'} width="10" height="10" />
                <IconThink width="14" height="14" />
                <span>思考结果</span>
              </button>
              {isThoughtExpanded && (
                <pre className="al-section-content al-thought">{step.lastThought}</pre>
              )}
            </div>
          )}

          {/* ── Tool Calls 区块 ── */}
          {step.toolCalls.length > 0 && (
            <div className="al-step-section">
              <div className="al-section-header al-section-header--static">
                <IconTool width="14" height="14" />
                <span>工具调用 ({step.toolCalls.length})</span>
              </div>
              <div className="al-tool-list">
                {step.toolCalls.map((tc, i) => {
                  const result = step.toolResults[i];
                  const isSuccess = result?.success;
                  return (
                    <div
                      key={i}
                      className={`al-tool-item ${isSuccess ? 'al-tool-item--success' : result ? 'al-tool-item--fail' : ''}`}
                    >
                      <div className="al-tool-name">
                        {isSuccess ? (
                          <IconCheck width="12" height="12" style={{ color: '#22c55e' }} />
                        ) : result ? (
                          <IconXCircle width="12" height="12" style={{ color: '#ef4444' }} />
                        ) : (
                          <IconPending width="12" height="12" style={{ color: '#6b7280' }} />
                        )}
                        <span>{tc.toolName || '未知工具'}</span>
                        {tc.purpose && <span className="al-tool-purpose">{tc.purpose}</span>}
                      </div>
                      {result && (
                        <div className="al-tool-result">
                          {result.toolOutput && (
                            <pre className="al-tool-output">{result.toolOutput.slice(0, 500)}</pre>
                          )}
                          {result.errorMessage && (
                            <div className="al-tool-error">{result.errorMessage}</div>
                          )}
                          {result.latencyMs > 0 && (
                            <span className="al-tool-time">
                              <IconClock width="10" height="10" />
                              {formatMs(result.latencyMs)}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Observe 区块（可折叠）── */}
          {step.lastObservation && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleObservation} type="button">
                <IconChevron direction={isObservationExpanded ? 'down' : 'right'} width="10" height="10" />
                <IconObserve width="14" height="14" />
                <span>观察结果</span>
              </button>
              {isObservationExpanded && (
                <pre className="al-section-content al-observation">{step.lastObservation}</pre>
              )}
            </div>
          )}

          {/* ── Evaluate 区块（可折叠）── */}
          {step.evaluationResult && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleEvaluation} type="button">
                <IconChevron direction={isEvaluationExpanded ? 'down' : 'right'} width="10" height="10" />
                <IconEvaluate width="14" height="14" />
                <span>评估结果</span>
                <span
                  className="al-verdict-badge"
                  style={{ backgroundColor: VERDICT_COLOR[step.evaluationResult.verdict] || '#666' }}
                >
                  {VERDICT_LABEL[step.evaluationResult.verdict] || step.evaluationResult.verdict}
                </span>
              </button>
              {isEvaluationExpanded && (
                <div className="al-section-content al-evaluation">
                  {step.evaluationResult.evaluationReason && (
                    <div className="al-eval-field">
                      <span className="al-eval-label">原因</span>
                      <span>{step.evaluationResult.evaluationReason}</span>
                    </div>
                  )}
                  {step.evaluationResult.gapAnalysis && (
                    <div className="al-eval-field">
                      <span className="al-eval-label">差距</span>
                      <span>{step.evaluationResult.gapAnalysis}</span>
                    </div>
                  )}
                  {step.evaluationResult.suggestion && (
                    <div className="al-eval-field">
                      <span className="al-eval-label">建议</span>
                      <span>{step.evaluationResult.suggestion}</span>
                    </div>
                  )}
                  {/* 验收条件逐条检查 */}
                  {step.evaluationResult.criteriaChecklist.length > 0 && (
                    <div className="al-eval-criteria">
                      <span className="al-eval-label">条件检查</span>
                      {step.evaluationResult.criteriaChecklist.map((c, i) => (
                        <div key={i} className="al-eval-criterion">
                          {c.met ? (
                            <IconCheck width="10" height="10" style={{ color: '#22c55e' }} />
                          ) : (
                            <IconXCircle width="10" height="10" style={{ color: '#ef4444' }} />
                          )}
                          <span>{c.criterion}</span>
                          {c.evidence && <span className="al-eval-evidence">{c.evidence}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
