/**
 * AgentGoalCard — 全局目标卡片组件。
 *
 * 做什么：展示锁定后的全局目标、验收标准、非目标声明和约束条件。
 *         位于面板顶部，作为视觉锚点，传达"目标不变"的核心语义。
 * 为什么这样做：Agent Loop 的第一条不变量是"全局目标不可变"，需要通过锁定态视觉语言表达。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.goal。
 * 边界条件：goal 可能为空字段，渲染时必须做空值保护。
 * 异常行为：无。
 */
import React from 'react';
import type { AgentLoopGoal } from '../../types/agentLoopWorkflow';
import { IconTarget, IconLock, IconChevron } from './icons';

interface AgentGoalCardProps {
  /** 全局目标投影 */
  goal: AgentLoopGoal;
  /** 是否展开详情 */
  expanded: boolean;
  /** 切换展开/收起 */
  onToggle: () => void;
}

/**
 * 全局目标卡片。
 * 做什么：渲染锁定态目标信息，支持收起/展开。
 * 视觉设计：锁定后显示锁定图标，背景色加深（#7c3aed），用视觉锚点传达"目标不变"语义。
 */
export const AgentGoalCard: React.FC<AgentGoalCardProps> = ({ goal, expanded, onToggle }) => {
  return (
    <div className={`al-goal-section ${goal.locked ? 'al-goal-section--locked' : ''}`}>
      {/* 目标头部：点击展开/收起 */}
      <button className="al-goal-header" onClick={onToggle} type="button">
        <span className="al-goal-chevron">
          <IconChevron direction={expanded ? 'down' : 'right'} width="12" height="12" />
        </span>
        <span className="al-goal-icon">
          <IconTarget width="16" height="16" />
        </span>
        <span className="al-goal-title">{goal.globalGoal || '目标锁定中...'}</span>
        {goal.locked && (
          <span className="al-goal-locked">
            <IconLock width="14" height="14" />
          </span>
        )}
      </button>

      {/* 目标详情（展开时显示） */}
      {expanded && (
        <div className="al-goal-details">
          {/* 详细描述 */}
          {goal.goalDefinition && (
            <div className="al-goal-field">
              <span className="al-goal-label">详细描述</span>
              <span className="al-goal-value">{goal.goalDefinition}</span>
            </div>
          )}

          {/* 验收标准 */}
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

          {/* 非目标声明 */}
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

          {/* 约束条件 */}
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
  );
};
