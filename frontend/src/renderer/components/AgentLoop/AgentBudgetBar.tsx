/**
 * AgentBudgetBar — 预算消耗进度条组件。
 *
 * 做什么：以进度条形式展示各类预算的消耗情况（Token、工具调用、重试、Replan）。
 * 为什么这样做：预算实时感知是 Agent Loop 的核心设计原则之一，超限会导致任务终止。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.budget。
 * 边界条件：max 值为 0 时进度条显示为 0%，避免除零错误。
 * 异常行为：无。
 */
import React from 'react';
import type { AgentBudgetState } from '../../types/agentLoopWorkflow';
import { IconGauge } from './icons';

interface AgentBudgetBarProps {
  /** 预算投影 */
  budget: AgentBudgetState;
}

/**
 * 单条预算进度项。
 * 做什么：渲染一条带标签的进度条。
 * 视觉设计：消耗超过 80% 时进度条变为琥珀色警告，达到 100% 时变为红色。
 */
const BudgetItem: React.FC<{
  label: string;
  used: number;
  max: number;
}> = ({ label, used, max }) => {
  /** 计算消耗百分比，避免除零 */
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0;
  /** 状态色：正常为紫色主色调，超过 80% 为琥珀色警告，达到 100% 为红色 */
  const barColor = pct >= 100 ? '#ef4444' : pct >= 80 ? '#f59e0b' : '#a855f7';

  return (
    <div className="al-budget-item">
      <div className="al-budget-item-header">
        <span className="al-budget-item-label">{label}</span>
        <span className="al-budget-item-count">
          {used}/{max}
        </span>
      </div>
      <div className="al-budget-item-track">
        <div
          className="al-budget-item-fill"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
    </div>
  );
};

/**
 * 预算消耗进度条容器。
 * 做什么：渲染四条平行进度条，分别对应 Token、工具调用、重试和 Replan。
 */
export const AgentBudgetBar: React.FC<AgentBudgetBarProps> = ({ budget }) => {
  return (
    <div className="al-budget-bar">
      <div className="al-budget-title">
        <IconGauge width="12" height="12" />
        <span>预算</span>
      </div>
      <div className="al-budget-grid">
        <BudgetItem label="工具调用" used={budget.toolCallsUsed} max={budget.maxToolCalls} />
        <BudgetItem label="重试" used={budget.stepRetriesUsed} max={budget.maxStepRetries} />
        <BudgetItem label="重规划" used={budget.replanCount} max={budget.maxReplanCount} />
      </div>
    </div>
  );
};
