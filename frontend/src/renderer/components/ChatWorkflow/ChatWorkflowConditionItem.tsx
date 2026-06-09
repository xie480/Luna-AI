import React from 'react';
import { CHAT_NODE_STATUS, CHAT_NODE_STATUS_LABEL, CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import type { ChatWorkflowNodeType } from '../../../shared/types';
import './ChatWorkflow.css';

/**
 * 条件节点展示项。
 * 做什么：展示条件节点是否进入、未进入原因以及折叠/展开详情。
 * 为什么这样做：Phase 8.5 的条件节点不是用户手动跳过，而是后端条件边评估结果，需要单独中性表达。
 * 输入输出：输入 interactionId、节点类型、条件结果和原因；输出 UI 展示项。
 * 边界条件：reason 为空时仅展示状态，不渲染展开按钮。
 * 异常行为：无。
 */
export const ChatWorkflowConditionItem: React.FC<{
  interactionId: string;
  nodeType: ChatWorkflowNodeType;
  conditionEntered?: boolean;
  reason?: string;
}> = ({ interactionId, nodeType, conditionEntered, reason }) => {
  const expanded = useChatWorkflowStore(
    (state) => (state.expandedConditionReasons[`${interactionId}:${nodeType}`] ?? false)
  );
  const toggleConditionReasonExpanded = useChatWorkflowStore((state) => state.toggleConditionReasonExpanded);

  /**
   * 计算条件节点展示状态文案。
   * 做什么：把后端布尔结果转成更适合用户阅读的中文状态。
   * 为什么这样做：条件未进入属于正常路由结果，必须避免失败语义。
   * 输入输出：输入 conditionEntered，输出中文状态文本。
   * 边界条件：undefined 代表尚未收到判断结果。
   * 异常行为：无。
   */
  const conditionStatusText = (() => {
    if (conditionEntered === true) {
      return '条件已进入';
    }
    if (conditionEntered === false) {
      return CHAT_NODE_STATUS_LABEL[CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION];
    }
    return '等待评估';
  })();

  return (
    <div className="chat-workflow-condition-item">
      <div className="chat-workflow-condition-item__header">
        <div className="chat-workflow-condition-item__title">
          {CHAT_WORKFLOW_NODE_LABEL[nodeType]} · {conditionStatusText}
        </div>
        {reason && (
          <button
            type="button"
            className="chat-workflow-condition-item__reason-btn"
            onClick={() => toggleConditionReasonExpanded(interactionId, nodeType)}
          >
            {expanded ? '收起原因' : '查看原因'}
          </button>
        )}
      </div>
      {reason && expanded && <div className="chat-workflow-condition-item__reason">{reason}</div>}
    </div>
  );
};
