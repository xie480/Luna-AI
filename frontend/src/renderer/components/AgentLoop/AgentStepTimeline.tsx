/**
 * AgentStepTimeline — Step 时间线容器组件。
 *
 * 做什么：以垂直时间线形式展示所有 Step 的执行过程，左侧为连接线 + 节点圆点。
 * 为什么这样做：时间线是表达步进式推进最直观的视觉形式，节点颜色映射步骤状态。
 * 输入输出：数据来源为 agentLoopStore.activeLoop.plan.steps。
 * 边界条件：steps 为空数组时不渲染时间线。
 * 异常行为：无。
 */
import React, { useRef, useEffect } from 'react';
import type { AgentStepProjection, AgentStepStatus } from '../../types/agentLoopWorkflow';
import { AgentStepCard } from './AgentStepCard';

// ============================================================
// 常量
// ============================================================

/** 步骤状态颜色映射（与赛博朋克全息流程图对齐） */
const STATUS_COLOR: Record<AgentStepStatus, string> = {
  pending: 'rgba(255, 255, 255, 0.25)',
  running: '#00ffff',
  passed: '#00fa9a',
  failed: '#ff003c',
  skipped: 'rgba(255, 255, 255, 0.15)',
};

// ============================================================
// Props
// ============================================================

interface AgentStepTimelineProps {
  /** 步骤列表 */
  steps: AgentStepProjection[];
  /** 当前执行步骤索引 */
  currentStepIndex: number;
  /** 步骤展开状态（按 stepId 索引） */
  expandedSteps: Record<string, boolean>;
  /** Think 展开状态 */
  expandedThoughts: Record<string, boolean>;
  /** Observe 展开状态 */
  expandedObservations: Record<string, boolean>;
  /** Evaluate 展开状态 */
  expandedEvaluations: Record<string, boolean>;
  /** 循环迭代展开状态，key 为 `${stepId}_${iterationIndex}` */
  expandedIterations: Record<string, boolean>;
  /** 切换步骤展开 */
  onToggleStep: (stepId: string) => void;
  /** 切换 Think 展开 */
  onToggleThought: (stepId: string) => void;
  /** 切换 Observe 展开 */
  onToggleObservation: (stepId: string) => void;
  /** 切换 Evaluate 展开 */
  onToggleEvaluation: (stepId: string) => void;
  /** 切换循环迭代展开 */
  onToggleIteration: (stepId: string, iterationIndex: number) => void;
}

// ============================================================
// 组件实现
// ============================================================

/**
 * Step 时间线容器。
 * 做什么：渲染垂直时间线，每一步由节点圆点 + 连接线 + StepCard 组成。
 * 视觉设计：
 *   - 节点圆点颜色映射步骤状态
 *   - 当前执行步骤高亮，已完成步骤降低透明度
 *   - running 状态节点播放脉冲动画
 */
export const AgentStepTimeline: React.FC<AgentStepTimelineProps> = ({
  steps,
  currentStepIndex,
  expandedSteps,
  expandedThoughts,
  expandedObservations,
  expandedEvaluations,
  expandedIterations,
  onToggleStep,
  onToggleThought,
  onToggleObservation,
  onToggleEvaluation,
  onToggleIteration,
}) => {
  /** 自动滚动到当前执行步骤的引用 */
  const currentStepRef = useRef<HTMLDivElement>(null);

  /**
   * 当 currentStepIndex 变化时，自动滚动到当前步骤。
   * 为什么这样做：长步骤列表中用户需要看到正在执行的步骤。
   */
  useEffect(() => {
    if (currentStepRef.current) {
      currentStepRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [currentStepIndex]);

  if (steps.length === 0) {
    return null;
  }

  return (
    <div className="al-timeline">
      {steps.map((step, index) => {
        const isCurrent = index === currentStepIndex;
        const isPast = index < currentStepIndex;
        const statusColor = STATUS_COLOR[step.status] || '#6b7280';

        return (
          <div
            key={step.stepId}
            ref={isCurrent ? currentStepRef : undefined}
            className={`al-timeline-item ${isCurrent ? 'al-timeline-item--current' : ''} ${isPast ? 'al-timeline-item--past' : ''}`}
          >
            {/* 左侧时间线：连接线 + 节点圆点 */}
            <div className="al-timeline-track">
              {/* 上半段连接线 */}
              {index > 0 && (
                <div
                  className="al-timeline-line al-timeline-line--top"
                  style={{ backgroundColor: isPast || isCurrent ? STATUS_COLOR[steps[index - 1].status] : 'rgba(255,255,255,0.08)' }}
                />
              )}
              {/* 节点圆点 */}
              <div
                className={`al-timeline-dot ${step.status === 'running' ? 'al-timeline-dot--pulse' : ''}`}
                style={{ borderColor: statusColor, backgroundColor: step.status === 'pending' ? 'transparent' : statusColor }}
              />
              {/* 下半段连接线 */}
              {index < steps.length - 1 && (
                <div
                  className="al-timeline-line al-timeline-line--bottom"
                  style={{ backgroundColor: isPast ? statusColor : 'rgba(255,255,255,0.08)' }}
                />
              )}
            </div>

            {/* 右侧卡片 */}
            <div className="al-timeline-content">
              <AgentStepCard
                step={step}
                index={index}
                isCurrent={isCurrent}
                isExpanded={!!expandedSteps[step.stepId]}
                isThoughtExpanded={!!expandedThoughts[step.stepId]}
                isObservationExpanded={!!expandedObservations[step.stepId]}
                isEvaluationExpanded={!!expandedEvaluations[step.stepId]}
                expandedIterations={expandedIterations}
                onToggle={() => onToggleStep(step.stepId)}
                onToggleThought={() => onToggleThought(step.stepId)}
                onToggleObservation={() => onToggleObservation(step.stepId)}
                onToggleEvaluation={() => onToggleEvaluation(step.stepId)}
                onToggleIteration={onToggleIteration}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};
