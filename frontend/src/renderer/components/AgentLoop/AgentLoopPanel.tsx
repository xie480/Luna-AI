/**
 * AgentLoopPanel — Agent Loop 万能循环模式面板（内嵌版）。
 *
 * 做什么：作为 Agent Loop 可视化的内嵌面板，展示 Step 时间线和最终验收结果。
 *         全局目标、计划版本、预算等全局数据已移至侧边栏固定区域（与智能规划模式一致）。
 *         本组件仅负责 Step Loop 可视化，作为特殊节点嵌入侧边栏 node-list 中。
 * 为什么这样做：全局数据（目标/预算）应固定在标题栏下方，不随画布滚动，
 *               Step 时间线和最终验收作为可滚动内容显示在画布中。
 * 输入输出：数据来源为 agentLoopStore.activeLoop。
 * 边界条件：activeLoop 为 null 时展示空状态提示。
 * 异常行为：无。
 */
import React from 'react';
import { useAgentLoopStore } from '../../stores/agentLoopStore';
import { AgentStepTimeline } from './AgentStepTimeline';
import { AgentFinalVerifyCard } from './AgentFinalVerifyCard';
import { TaskControlBar } from '../DagWorkflow/TaskControlBar';
import { IconAgentLoop } from './icons';
import './AgentLoopPanel.css';

// ============================================================
// 主面板组件
// ============================================================

/**
 * Agent Loop 内嵌面板。
 * 做什么：组合 StepTimeline 和 FinalVerifyCard，展示步进执行过程。
 * 视觉设计：严格沿用赛博朋克视觉语言，禁止 emoji，所有图标使用 SVG。
 * 注意：本组件不包含工具栏和全局数据区域，这些由侧边栏固定区域负责。
 */
export const AgentLoopPanel: React.FC = () => {
  const activeLoop = useAgentLoopStore((s) => s.activeLoop);
  const expandedSteps = useAgentLoopStore((s) => s.expandedSteps);
  const toggleStepExpanded = useAgentLoopStore((s) => s.toggleStepExpanded);
  const expandedThoughts = useAgentLoopStore((s) => s.expandedThoughts);
  const toggleThoughtExpanded = useAgentLoopStore((s) => s.toggleThoughtExpanded);
  const expandedObservations = useAgentLoopStore((s) => s.expandedObservations);
  const toggleObservationExpanded = useAgentLoopStore((s) => s.toggleObservationExpanded);
  const expandedEvaluations = useAgentLoopStore((s) => s.expandedEvaluations);
  const toggleEvaluationExpanded = useAgentLoopStore((s) => s.toggleEvaluationExpanded);
  const expandedIterations = useAgentLoopStore((s) => s.expandedIterations);
  const toggleIterationExpanded = useAgentLoopStore((s) => s.toggleIterationExpanded);

  // ── 空状态 ──
  if (!activeLoop) {
    return (
      <div className="al-panel al-panel--empty">
        <div className="al-panel-empty-icon">
          <IconAgentLoop width="48" height="48" />
        </div>
        <div className="al-panel-empty-text">等待 Agent Loop 引擎启动...</div>
      </div>
    );
  }

  const { plan, finalVerification } = activeLoop;

  /** 已完成步骤数 */
  const completedSteps = plan.steps.filter((s) => s.status === 'passed').length;
  /** 失败步骤数 */
  const failedSteps = plan.steps.filter((s) => s.status === 'failed').length;

  /** 是否正在执行中（用于触发发光边框动画） */
  const isRunning = activeLoop.status === 'executing' || activeLoop.status === 'replanning' || activeLoop.status === 'verifying';

  return (
    <div className={`al-panel al-panel--embedded${isRunning ? ' al-panel--running' : ''}`}>
      {/* ═══ Phase 10: 任务控制栏 ═══ */}
      <TaskControlBar />

      {/* ═══ Step 时间线 ═══ */}
      <div className="al-steps-container">
        <AgentStepTimeline
          steps={plan.steps}
          currentStepIndex={plan.currentStepIndex}
          expandedSteps={expandedSteps}
          expandedThoughts={expandedThoughts}
          expandedObservations={expandedObservations}
          expandedEvaluations={expandedEvaluations}
          expandedIterations={expandedIterations}
          onToggleStep={toggleStepExpanded}
          onToggleThought={toggleThoughtExpanded}
          onToggleObservation={toggleObservationExpanded}
          onToggleEvaluation={toggleEvaluationExpanded}
          onToggleIteration={toggleIterationExpanded}
        />
      </div>

      {/* ═══ 最终验收卡片 ═══ */}
      {finalVerification && (
        <AgentFinalVerifyCard
          verification={finalVerification}
          totalSteps={plan.steps.length}
          succeededSteps={completedSteps}
          failedSteps={failedSteps}
          elapsedMs={activeLoop.elapsedMs}
          planVersion={plan.planVersion}
        />
      )}
    </div>
  );
};
