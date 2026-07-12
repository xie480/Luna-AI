/**
 * AgentPlanHeader — 计划头部组件。
 *
 * 做什么：展示当前计划版本号、步骤总数、执行进度和 Replan 历史。
 * 为什么这样做：Agent Loop 的第二条不变量是"步骤可变"，需要通过版本号和变更高亮传达。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.plan。
 * 边界条件：replanHistory 可能为空数组，currentStepIndex 可能超出 steps 长度。
 * 异常行为：无。
 */
import React, { useState } from 'react';
import type { AgentLoopPlan } from '../../types/agentLoopWorkflow';
import { IconBranch, IconChevron } from './icons';

interface AgentPlanHeaderProps {
  /** 计划投影 */
  plan: AgentLoopPlan;
  /** 已完成步骤数 */
  completedSteps: number;
}

/**
 * 计划头部。
 * 做什么：渲染版本号、进度和 Replan 历史。
 * 视觉设计：左侧显示 planVersion，右侧显示进度，Replan 记录可展开。
 */
export const AgentPlanHeader: React.FC<AgentPlanHeaderProps> = ({ plan, completedSteps }) => {
  /** Replan 历史展开状态 */
  const [replanExpanded, setReplanExpanded] = useState(false);

  return (
    <div className="al-plan-header">
      {/* 版本与进度 */}
      <div className="al-plan-header-main">
        <div className="al-plan-version">
          <IconBranch width="14" height="14" />
          <span className="al-plan-version-text">Plan v{plan.planVersion}</span>
        </div>
        <div className="al-plan-progress">
          <span className="al-plan-progress-count">
            {completedSteps}/{plan.steps.length}
          </span>
          <span className="al-plan-progress-label">steps</span>
        </div>
      </div>

      {/* Replan 历史（可展开） */}
      {plan.replanHistory.length > 0 && (
        <div className="al-replan-section">
          <button
            className="al-replan-header"
            onClick={() => setReplanExpanded((v) => !v)}
            type="button"
          >
            <IconChevron direction={replanExpanded ? 'down' : 'right'} width="10" height="10" />
            <IconBranch width="12" height="12" />
            <span>重规划历史 ({plan.replanHistory.length})</span>
          </button>
          {replanExpanded && (
            <div className="al-replan-list">
              {plan.replanHistory.map((record, i) => (
                <div key={i} className="al-replan-record">
                  <span className="al-replan-version">
                    v{record.fromVersion} → v{record.toVersion}
                  </span>
                  <span className="al-replan-reason" onMouseDown={(e) => e.stopPropagation()}>{record.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
