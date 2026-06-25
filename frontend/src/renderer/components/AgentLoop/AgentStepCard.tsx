/**
 * AgentStepCard — 单步卡片组件（含循环迭代历史展示）。
 *
 * 做什么：展示单个 Step 的完整执行详情，包括：
 *   1. 已完成的循环迭代历史（loopIterations）
 *   2. 当前活跃迭代的实时数据（lastThought/toolCalls 等 live 字段）
 *   每次循环迭代展示 Think → ToolCalls → Observe → Evaluate 全过程。
 * 为什么这样做：一个 Step 可能经历多次循环（fail → repair → re-think → re-execute），
 *               用户需要看到完整的循环迭代过程，而非只看到最新一次。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.plan.steps[i]。
 * 边界条件：所有执行详情字段都可能为空，渲染时必须做空值保护。
 * 异常行为：无。
 */
import React from 'react';
import type {
  AgentStepProjection,
  AgentStepStatus,
  AgentLoopIteration,
  AgentToolCall,
  AgentToolResult,
  AgentStepEvaluation,
} from '../../types/agentLoopWorkflow';
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
  IconLoop,
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

/**
 * 格式化工具输出为可读文本。
 * 做什么：将 JSON 字符串尝试解析并截断展示。
 * 边界条件：超长输出截断到 maxLen 字符。
 */
function formatToolOutput(output: string, maxLen = 600): string {
  if (!output) return '';
  try {
    const parsed = JSON.parse(output);
    const formatted = JSON.stringify(parsed, null, 2);
    return formatted.length > maxLen ? formatted.slice(0, maxLen) + '...' : formatted;
  } catch {
    return output.length > maxLen ? output.slice(0, maxLen) + '...' : output;
  }
}

// ============================================================
// 工具调用列表渲染组件（提取复用）
// ============================================================

interface ToolCallListProps {
  toolCalls: AgentToolCall[];
  toolResults: AgentToolResult[];
}

/**
 * 工具调用列表组件。
 * 做什么：渲染工具调用详情，包含调用原因（purpose）、执行结果（toolOutput）、耗时（latencyMs）。
 * 为什么这样做：tool 调用详情在循环迭代历史和当前迭代中复用。
 */
const ToolCallList: React.FC<ToolCallListProps> = ({ toolCalls, toolResults }) => {
  if (toolCalls.length === 0) return null;

  return (
    <div className="al-step-section">
      <div className="al-section-header al-section-header--static">
        <IconTool width="14" height="14" />
        <span>工具调用 ({toolCalls.length})</span>
      </div>
      <div className="al-tool-list">
        {toolCalls.map((tc, i) => {
          const result = toolResults[i];
          const isSuccess = result?.success;
          return (
            <div
              key={i}
              className={`al-tool-item ${isSuccess ? 'al-tool-item--success' : result ? 'al-tool-item--fail' : ''}`}
            >
              {/* 工具名 + 状态图标 */}
              <div className="al-tool-name">
                {isSuccess ? (
                  <IconCheck width="12" height="12" style={{ color: '#22c55e' }} />
                ) : result ? (
                  <IconXCircle width="12" height="12" style={{ color: '#ef4444' }} />
                ) : (
                  <IconPending width="12" height="12" style={{ color: '#6b7280' }} />
                )}
                <span className="al-tool-name-text">{tc.toolName || '未知工具'}</span>
                {tc.skillName && (
                  <span className="al-tool-skill-badge">{tc.skillName}</span>
                )}
              </div>

              {/* 调用原因（purpose） */}
              {tc.purpose && (
                <div className="al-tool-purpose-row">
                  <span className="al-tool-purpose-label">原因</span>
                  <span className="al-tool-purpose-text">{tc.purpose}</span>
                </div>
              )}

              {/* 调用参数（折叠展示） */}
              {tc.parameters && Object.keys(tc.parameters).length > 0 && (
                <div className="al-tool-params-row">
                  <pre className="al-tool-params">{JSON.stringify(tc.parameters, null, 2).slice(0, 300)}</pre>
                </div>
              )}

              {/* 执行结果 */}
              {result && (
                <div className="al-tool-result">
                  {result.toolOutput && result.toolOutput !== '{}' && (
                    <pre className="al-tool-output">{formatToolOutput(result.toolOutput)}</pre>
                  )}
                  {result.errorMessage && (
                    <div className="al-tool-error">{result.errorMessage}</div>
                  )}
                  <div className="al-tool-meta">
                    {result.latencyMs > 0 && (
                      <span className="al-tool-time">
                        <IconClock width="10" height="10" />
                        {formatMs(result.latencyMs)}
                      </span>
                    )}
                    {result.retryCount > 0 && (
                      <span className="al-tool-retry">
                        <IconRetry width="10" height="10" />
                        重试 {result.retryCount}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ============================================================
// 评估结果渲染组件（提取复用）
// ============================================================

interface EvaluationBlockProps {
  evaluationResult: AgentStepEvaluation;
  isExpanded: boolean;
  onToggle: () => void;
}

/**
 * 评估结果区块组件。
 * 做什么：渲染 Step 评估结果，包含结论、原因、差距分析、建议和条件检查清单。
 */
const EvaluationBlock: React.FC<EvaluationBlockProps> = ({ evaluationResult, isExpanded, onToggle }) => (
  <div className="al-step-section">
    <button className="al-section-header" onClick={onToggle} type="button">
      <IconChevron direction={isExpanded ? 'down' : 'right'} width="10" height="10" />
      <IconEvaluate width="14" height="14" />
      <span>评估结果</span>
      <span
        className="al-verdict-badge"
        style={{ backgroundColor: VERDICT_COLOR[evaluationResult.verdict] || '#666' }}
      >
        {VERDICT_LABEL[evaluationResult.verdict] || evaluationResult.verdict}
      </span>
    </button>
    {isExpanded && (
      <div className="al-section-content al-evaluation">
        {evaluationResult.evaluationReason && (
          <div className="al-eval-field">
            <span className="al-eval-label">原因</span>
            <span>{evaluationResult.evaluationReason}</span>
          </div>
        )}
        {evaluationResult.gapAnalysis && (
          <div className="al-eval-field">
            <span className="al-eval-label">差距</span>
            <span>{evaluationResult.gapAnalysis}</span>
          </div>
        )}
        {evaluationResult.suggestion && (
          <div className="al-eval-field">
            <span className="al-eval-label">建议</span>
            <span>{evaluationResult.suggestion}</span>
          </div>
        )}
        {evaluationResult.criteriaChecklist.length > 0 && (
          <div className="al-eval-criteria">
            <span className="al-eval-label">条件检查</span>
            {evaluationResult.criteriaChecklist.map((c, i) => (
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
);

// ============================================================
// 循环迭代卡片组件
// ============================================================

interface IterationCardProps {
  /** 迭代数据快照 */
  iteration: AgentLoopIteration;
  /** 是否为最新迭代（当前活跃） */
  isLatest: boolean;
  /** 是否展开 */
  isExpanded: boolean;
  /** 评估展开状态 */
  isEvalExpanded: boolean;
  /** 切换展开 */
  onToggle: () => void;
  /** 切换评估展开 */
  onToggleEval: () => void;
}

/**
 * 单次循环迭代卡片。
 * 做什么：渲染一次完整的 Think → ToolCalls → Observe → Evaluate 循环。
 */
const IterationCard: React.FC<IterationCardProps> = ({
  iteration,
  isLatest,
  isExpanded,
  isEvalExpanded,
  onToggle,
  onToggleEval,
}) => (
  <div className={`al-iteration ${isLatest ? 'al-iteration--latest' : ''}`}>
    {/* 迭代头部 */}
    <button className="al-iteration-header" onClick={onToggle} type="button">
      <IconLoop width="12" height="12" />
      <span className="al-iteration-label">
        第 {iteration.iterationIndex} 轮循环
        {isLatest && <span className="al-iteration-latest-badge">当前</span>}
      </span>
      {iteration.latencyMs !== undefined && iteration.latencyMs > 0 && (
        <span className="al-step-time">
          <IconClock width="10" height="10" />
          {formatMs(iteration.latencyMs)}
        </span>
      )}
      {iteration.evaluationResult && (
        <span
          className="al-verdict-badge al-verdict-badge--sm"
          style={{ backgroundColor: VERDICT_COLOR[iteration.evaluationResult.verdict] || '#666' }}
        >
          {VERDICT_LABEL[iteration.evaluationResult.verdict] || iteration.evaluationResult.verdict}
        </span>
      )}
      <span className="al-step-chevron">
        <IconChevron direction={isExpanded ? 'down' : 'right'} width="10" height="10" />
      </span>
    </button>

    {/* 迭代详情 */}
    {isExpanded && (
      <div className="al-iteration-details">
        {/* Think */}
        {iteration.thought && (
          <div className="al-step-section al-step-section--compact">
            <div className="al-section-header al-section-header--static">
              <IconThink width="12" height="12" />
              <span>思考结果</span>
            </div>
            <pre className="al-section-content al-thought al-thought--compact">{iteration.thought}</pre>
          </div>
        )}

        {/* Tool Calls */}
        <ToolCallList toolCalls={iteration.toolCalls} toolResults={iteration.toolResults} />

        {/* Observe */}
        {iteration.observation && (
          <div className="al-step-section al-step-section--compact">
            <div className="al-section-header al-section-header--static">
              <IconObserve width="12" height="12" />
              <span>观察结果</span>
            </div>
            <pre className="al-section-content al-observation al-observation--compact">{iteration.observation}</pre>
          </div>
        )}

        {/* Evaluate */}
        {iteration.evaluationResult && (
          <EvaluationBlock
            evaluationResult={iteration.evaluationResult}
            isExpanded={isEvalExpanded}
            onToggle={onToggleEval}
          />
        )}
      </div>
    )}
  </div>
);

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
  /** 循环迭代展开状态（key: `${stepId}_${iterationIndex}`） */
  expandedIterations: Record<string, boolean>;
  /** 切换整体展开/折叠 */
  onToggle: () => void;
  /** 切换 Think 展开 */
  onToggleThought: () => void;
  /** 切换 Observe 展开 */
  onToggleObservation: () => void;
  /** 切换 Evaluate 展开 */
  onToggleEvaluation: () => void;
  /** 切换循环迭代展开 */
  onToggleIteration: (stepId: string, iterationIndex: number) => void;
}

// ============================================================
// 组件实现
// ============================================================

/**
 * 单步卡片。
 * 做什么：渲染一个可展开的步骤卡片，支持展示完整的循环迭代历史。
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
  expandedIterations,
  onToggle,
  onToggleThought,
  onToggleObservation,
  onToggleEvaluation,
  onToggleIteration,
}) => {
  /** 已完成的循环迭代数 */
  const iterationCount = step.loopIterations.length;
  /** 当前活跃迭代的索引（从 1 开始） */
  const currentIterIdx = step.currentIterationIndex || 1;
  /** 是否有多次循环迭代（展开迭代历史有意义） */
  const hasMultipleIterations = iterationCount > 0;
  /** 是否有当前活跃迭代的实时数据（正在执行中） */
  const hasActiveIterationData = step.lastThought || step.toolCalls.length > 0 || step.lastObservation;
  /** 是否有可展开的内容 */
  const hasContent = hasMultipleIterations || hasActiveIterationData;

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
        {/* 循环迭代次数标记 */}
        {hasMultipleIterations && (
          <span className="al-step-loop-badge" title={`经历了 ${iterationCount} 轮循环`}>
            <IconLoop width="11" height="11" />
            {iterationCount}
          </span>
        )}
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

          {/* ═══ 循环迭代历史 ═══ */}
          {hasMultipleIterations && (
            <div className="al-iterations-container">
              <div className="al-iterations-header">
                <IconLoop width="14" height="14" />
                <span>循环迭代记录 ({iterationCount} 轮)</span>
              </div>
              {step.loopIterations.map((iteration) => {
                const iterKey = `${step.stepId}_${iteration.iterationIndex}`;
                return (
                  <IterationCard
                    key={iterKey}
                    iteration={iteration}
                    isLatest={false}
                    isExpanded={!!expandedIterations[iterKey]}
                    isEvalExpanded={!!expandedIterations[`${iterKey}_eval`]}
                    onToggle={() => onToggleIteration(step.stepId, iteration.iterationIndex)}
                    onToggleEval={() => onToggleIteration(step.stepId, -(iteration.iterationIndex))}
                  />
                );
              })}
            </div>
          )}

          {/* ═══ 当前活跃迭代（实时数据）═══ */}
          {hasActiveIterationData && (
            <div className="al-iterations-container al-iterations-container--active">
              <div className="al-iterations-header">
                <IconLoop width="14" height="14" />
                <span>
                  当前迭代 (第 {currentIterIdx} 轮)
                  {step.status === 'running' && <span className="al-iteration-running-dot" />}
                </span>
              </div>

              {/* Think */}
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

              {/* Tool Calls */}
              <ToolCallList toolCalls={step.toolCalls} toolResults={step.toolResults} />

              {/* Observe */}
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

              {/* Evaluate */}
              {step.evaluationResult && (
                <EvaluationBlock
                  evaluationResult={step.evaluationResult}
                  isExpanded={isEvaluationExpanded}
                  onToggle={onToggleEvaluation}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
