/**
 * AgentLoopPanel — Agent Loop 万能循环模式主面板。
 *
 * 做什么：作为 Agent Loop 可视化的顶层容器，展示全局目标、步骤列表和最终验收。
 *         全局目标区域固定在面板标题栏下方，支持收起/展开。
 * 为什么这样做：Agent Loop 模式需要独立的面板来承载 Goal → Plan → StepLoop → FinalVerify 的可视化结构。
 * 输入输出：数据来源为 agentLoopStore.activeLoop。
 * 边界条件：activeLoop 为 null 时展示空状态提示。
 */
import React, { useCallback } from 'react';
import { useAgentLoopStore } from '../../stores/agentLoopStore';
import { AGENT_LOOP_STATUS_LABEL } from '../../types/agentLoopWorkflow';
import type { AgentStepProjection } from '../../types/agentLoopWorkflow';
import './AgentLoopPanel.css';

// ============================================================
// 辅助：状态颜色映射
// ============================================================
const STATUS_COLOR: Record<string, string> = {
  pending: '#666',
  running: '#4fc3f7',
  passed: '#66bb6a',
  failed: '#ef5350',
  skipped: '#999',
  goal_locking: '#ffb74d',
  planning: '#4fc3f7',
  executing: '#4fc3f7',
  replanning: '#ff9800',
  verifying: '#ab47bc',
  completed: '#66bb6a',
  completed_with_gaps: '#ffb74d',
  terminated: '#ef5350',
  budget_exhausted: '#ef5350',
};

const VERDICT_COLOR: Record<string, string> = {
  pass: '#66bb6a',
  fail: '#ef5350',
  partial: '#ffb74d',
  needs_replan: '#ff9800',
};

const VERDICT_LABEL: Record<string, string> = {
  pass: '通过',
  fail: '失败',
  partial: '部分完成',
  needs_replan: '需重规划',
};

// ============================================================
// 主面板组件
// ============================================================

export const AgentLoopPanel: React.FC = () => {
  const activeLoop = useAgentLoopStore((s) => s.activeLoop);
  const clearLoop = useAgentLoopStore((s) => s.clearLoop);
  const goalExpanded = useAgentLoopStore((s) => s.goalExpanded);
  const toggleGoalExpanded = useAgentLoopStore((s) => s.toggleGoalExpanded);
  const expandedSteps = useAgentLoopStore((s) => s.expandedSteps);
  const toggleStepExpanded = useAgentLoopStore((s) => s.toggleStepExpanded);
  const expandedThoughts = useAgentLoopStore((s) => s.expandedThoughts);
  const toggleThoughtExpanded = useAgentLoopStore((s) => s.toggleThoughtExpanded);
  const expandedObservations = useAgentLoopStore((s) => s.expandedObservations);
  const toggleObservationExpanded = useAgentLoopStore((s) => s.toggleObservationExpanded);
  const expandedEvaluations = useAgentLoopStore((s) => s.expandedEvaluations);
  const toggleEvaluationExpanded = useAgentLoopStore((s) => s.toggleEvaluationExpanded);

  const formatMs = useCallback((ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
  }, []);

  if (!activeLoop) {
    return (
      <div className="al-panel al-panel--empty">
        <div className="al-panel-empty-text">暂无 Agent Loop 任务</div>
      </div>
    );
  }

  const { goal, plan, budget, status, finalVerification, elapsedMs } = activeLoop;

  return (
    <div className="al-panel">
      {/* ═══ 顶部工具栏 ═══ */}
      <div className="al-toolbar">
        <div className="al-toolbar-left">
          <span className="al-toolbar-icon">🔄</span>
          <span className="al-toolbar-title">Agent Loop</span>
          <span
            className="al-status-badge"
            style={{ backgroundColor: STATUS_COLOR[status] || '#666' }}
          >
            {AGENT_LOOP_STATUS_LABEL[status] || status}
          </span>
          {elapsedMs !== undefined && (
            <span className="al-toolbar-time">{formatMs(elapsedMs)}</span>
          )}
        </div>
        <button className="al-toolbar-close" onClick={clearLoop} type="button">✕</button>
      </div>

      {/* ═══ 全局目标区域（可收起展开）═══ */}
      <div className="al-goal-section">
        <button className="al-goal-header" onClick={toggleGoalExpanded} type="button">
          <span className="al-goal-chevron">{goalExpanded ? '▼' : '▶'}</span>
          <span className="al-goal-icon">🎯</span>
          <span className="al-goal-title">{goal.globalGoal || '目标锁定中...'}</span>
          {goal.locked && <span className="al-goal-locked">🔒</span>}
        </button>
        {goalExpanded && (
          <div className="al-goal-details">
            {goal.goalDefinition && (
              <div className="al-goal-field">
                <span className="al-goal-label">详细描述</span>
                <span className="al-goal-value">{goal.goalDefinition}</span>
              </div>
            )}
            {goal.acceptanceCriteria.length > 0 && (
              <div className="al-goal-field">
                <span className="al-goal-label">验收标准</span>
                <ul className="al-goal-list">
                  {goal.acceptanceCriteria.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
            {goal.nonGoals.length > 0 && (
              <div className="al-goal-field">
                <span className="al-goal-label">非目标</span>
                <ul className="al-goal-list al-goal-list--neg">
                  {goal.nonGoals.map((ng, i) => (
                    <li key={i}>{ng}</li>
                  ))}
                </ul>
              </div>
            )}
            {goal.constraints.length > 0 && (
              <div className="al-goal-field">
                <span className="al-goal-label">约束条件</span>
                <div className="al-goal-tags">
                  {goal.constraints.map((c, i) => (
                    <span key={i} className="al-goal-tag">{c}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ═══ 预算状态栏 ═══ */}
      <div className="al-budget-bar">
        <span title="工具调用">🔧 {budget.toolCallsUsed}/{budget.maxToolCalls}</span>
        <span title="重试次数">🔁 {budget.stepRetriesUsed}</span>
        <span title="重规划次数">📐 {budget.replanCount}/{budget.maxReplanCount}</span>
        <span title="计划版本">v{plan.planVersion}</span>
        <span title="当前步骤">Step {plan.currentStepIndex + 1}/{plan.steps.length}</span>
      </div>

      {/* ═══ 步骤列表 ═══ */}
      <div className="al-steps-container">
        {plan.steps.map((step, index) => (
          <StepCard
            key={step.stepId}
            step={step}
            index={index}
            isCurrent={index === plan.currentStepIndex}
            isExpanded={!!expandedSteps[step.stepId]}
            isThoughtExpanded={!!expandedThoughts[step.stepId]}
            isObservationExpanded={!!expandedObservations[step.stepId]}
            isEvaluationExpanded={!!expandedEvaluations[step.stepId]}
            onToggle={() => toggleStepExpanded(step.stepId)}
            onToggleThought={() => toggleThoughtExpanded(step.stepId)}
            onToggleObservation={() => toggleObservationExpanded(step.stepId)}
            onToggleEvaluation={() => toggleEvaluationExpanded(step.stepId)}
            formatMs={formatMs}
          />
        ))}
      </div>

      {/* ═══ 最终验收 ═══ */}
      {finalVerification && (
        <div className="al-final-section">
          <div className="al-final-header">
            <span className="al-final-icon">
              {finalVerification.allCriteriaMet ? '✅' : '⚠️'}
            </span>
            <span className="al-final-title">
              {finalVerification.allCriteriaMet ? '验收通过' : '部分标准未满足'}
            </span>
            <span className="al-final-status">{finalVerification.status}</span>
          </div>
          {finalVerification.report && (
            <div className="al-final-report">{finalVerification.report}</div>
          )}
        </div>
      )}

      {/* ═══ Replan 历史 ═══ */}
      {plan.replanHistory.length > 0 && (
        <div className="al-replan-section">
          <div className="al-replan-header">📐 重规划历史 ({plan.replanHistory.length})</div>
          {plan.replanHistory.map((record, i) => (
            <div key={i} className="al-replan-record">
              <span className="al-replan-version">v{record.fromVersion} → v{record.toVersion}</span>
              <span className="al-replan-reason">{record.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ============================================================
// StepCard — 单步详情卡片
// ============================================================

interface StepCardProps {
  step: AgentStepProjection;
  index: number;
  isCurrent: boolean;
  isExpanded: boolean;
  isThoughtExpanded: boolean;
  isObservationExpanded: boolean;
  isEvaluationExpanded: boolean;
  onToggle: () => void;
  onToggleThought: () => void;
  onToggleObservation: () => void;
  onToggleEvaluation: () => void;
  formatMs: (ms: number) => string;
}

const StepCard: React.FC<StepCardProps> = ({
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
  formatMs,
}) => {
  const statusColor = STATUS_COLOR[step.status] || '#666';
  const hasContent = step.lastThought || step.toolCalls.length > 0 || step.lastObservation || step.evaluationResult;

  return (
    <div className={`al-step-card ${isCurrent ? 'al-step-card--current' : ''} ${isExpanded ? 'al-step-card--expanded' : ''}`}>
      {/* 步骤头部 */}
      <button className="al-step-header" onClick={onToggle} type="button">
        <span className="al-step-index">{index + 1}</span>
        <span className="al-step-status-dot" style={{ backgroundColor: statusColor }} />
        <span className="al-step-title">{step.title || `步骤 ${index + 1}`}</span>
        <span className="al-step-status-text">{step.status}</span>
        {step.latencyMs !== undefined && (
          <span className="al-step-time">{formatMs(step.latencyMs)}</span>
        )}
        {step.retryCount > 0 && (
          <span className="al-step-retry">🔁{step.retryCount}</span>
        )}
        {step.repairCount > 0 && (
          <span className="al-step-repair">🔧{step.repairCount}</span>
        )}
        <span className="al-step-chevron">{isExpanded ? '▼' : '▶'}</span>
      </button>

      {/* 步骤详情（展开时显示） */}
      {isExpanded && (
        <div className="al-step-details">
          {/* 意图和预期输出 */}
          {step.intent && (
            <div className="al-step-field">
              <span className="al-step-label">意图</span>
              <span className="al-step-value">{step.intent}</span>
            </div>
          )}
          {step.expectedOutput && (
            <div className="al-step-field">
              <span className="al-step-label">预期输出</span>
              <span className="al-step-value">{step.expectedOutput}</span>
            </div>
          )}
          {step.riskNotes && (
            <div className="al-step-field">
              <span className="al-step-label">⚠️ 风险</span>
              <span className="al-step-value">{step.riskNotes}</span>
            </div>
          )}

          {/* 思考结果（可折叠） */}
          {step.lastThought && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleThought} type="button">
                <span>{isThoughtExpanded ? '▼' : '▶'}</span>
                <span>💭 思考结果</span>
              </button>
              {isThoughtExpanded && (
                <pre className="al-section-content al-thought">{step.lastThought}</pre>
              )}
            </div>
          )}

          {/* 工具调用 */}
          {step.toolCalls.length > 0 && (
            <div className="al-step-section">
              <div className="al-section-header al-section-header--static">
                <span>🔧 工具调用 ({step.toolCalls.length})</span>
              </div>
              <div className="al-tool-list">
                {step.toolCalls.map((tc, i) => {
                  const result = step.toolResults[i];
                  return (
                    <div key={i} className={`al-tool-item ${result?.success ? 'al-tool-item--success' : result ? 'al-tool-item--fail' : ''}`}>
                      <div className="al-tool-name">
                        <span className="al-tool-icon">{result?.success ? '✅' : result ? '❌' : '⏳'}</span>
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
                            <span className="al-tool-time">{formatMs(result.latencyMs)}</span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 观察结果（可折叠） */}
          {step.lastObservation && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleObservation} type="button">
                <span>{isObservationExpanded ? '▼' : '▶'}</span>
                <span>👁️ 观察结果</span>
              </button>
              {isObservationExpanded && (
                <pre className="al-section-content al-observation">{step.lastObservation}</pre>
              )}
            </div>
          )}

          {/* 评估结果（可折叠） */}
          {step.evaluationResult && (
            <div className="al-step-section">
              <button className="al-section-header" onClick={onToggleEvaluation} type="button">
                <span>{isEvaluationExpanded ? '▼' : '▶'}</span>
                <span>📊 评估结果</span>
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
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
