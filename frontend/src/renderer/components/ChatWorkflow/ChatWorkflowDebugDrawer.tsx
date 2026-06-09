import React from 'react';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { ChatWorkflowTimeline } from './ChatWorkflowTimeline';
import './ChatWorkflow.css';

/**
 * Chat Workflow 调试抽屉内容组件。
 * 做什么：在诊断面板中展示当前 trace 的 workflow 摘要与节点时间线。
 * 为什么这样做：Phase 8.5 要求开发者能看到条件判断、降级原因和计划时间线，但不需要完整 DAG 图。
 * 输入输出：输入当前 activePlan 与 debugTimeline，输出只读调试内容。
 * 边界条件：无活跃计划时展示空态，不猜测历史 trace。
 * 异常行为：无。
 */
export const ChatWorkflowDebugDrawer: React.FC = () => {
  const activePlan = useChatWorkflowStore((state) => state.activePlan);
  const nodes = useChatWorkflowStore((state) =>
    activePlan ? state.nodesByInteractionId[activePlan.interactionId] || [] : []
  );

  if (!activePlan) {
    return <div className="chat-workflow-debug-drawer__empty">当前没有活跃的 Chat Workflow 调试数据。</div>;
  }

  return (
    <div className="chat-workflow-debug-drawer">
      <div className="chat-workflow-debug-drawer__summary">
        <div className="chat-workflow-debug-drawer__summary-card">
          <div className="chat-workflow-debug-drawer__summary-label">Trace ID</div>
          <div className="chat-workflow-debug-drawer__summary-value">{activePlan.traceId}</div>
        </div>
        <div className="chat-workflow-debug-drawer__summary-card">
          <div className="chat-workflow-debug-drawer__summary-label">Interaction ID</div>
          <div className="chat-workflow-debug-drawer__summary-value">{activePlan.interactionId}</div>
        </div>
        <div className="chat-workflow-debug-drawer__summary-card">
          <div className="chat-workflow-debug-drawer__summary-label">节点数量</div>
          <div className="chat-workflow-debug-drawer__summary-value">{nodes.length}</div>
        </div>
      </div>

      <ChatWorkflowTimeline traceId={activePlan.traceId} />
    </div>
  );
};
