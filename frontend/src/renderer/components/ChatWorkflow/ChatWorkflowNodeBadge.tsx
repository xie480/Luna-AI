import React from 'react';
import { CHAT_NODE_STATUS, CHAT_NODE_STATUS_LABEL, CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import type { ChatNodeProjection } from '../../types/chatWorkflow';
import './ChatWorkflow.css';

/**
 * 节点状态徽标组件。
 * 做什么：以统一的颜色语义展示某个 workflow 节点的名称、状态和耗时。
 * 为什么这样做：步骤条、元数据面板和调试区域都需要复用相同的节点视觉表达，避免重复造轮子。
 * 输入输出：输入节点投影，输出为只读展示组件。
 * 边界条件：耗时为空时不展示延迟文本；条件未进入按照中性色展示。
 * 异常行为：无。
 */
export const ChatWorkflowNodeBadge: React.FC<{ node: ChatNodeProjection }> = ({ node }) => {
  /**
   * 根据节点状态映射 BEM 样式修饰符。
   * 做什么：把状态常量映射为样式类名片段。
   * 为什么这样做：避免样式层直接依赖后端状态原始字符串。
   * 输入输出：输入节点状态，输出样式修饰符。
   * 边界条件：未知状态回退到 pending。
   * 异常行为：无。
   */
  const variant = (() => {
    switch (node.status) {
      case CHAT_NODE_STATUS.RUNNING:
        return 'running';
      case CHAT_NODE_STATUS.SUCCEEDED:
        return 'succeeded';
      case CHAT_NODE_STATUS.DEGRADED:
        return 'degraded';
      case CHAT_NODE_STATUS.FAILED:
        return 'failed';
      case CHAT_NODE_STATUS.NOT_ENTERED_BY_CONDITION:
        return 'not-entered';
      default:
        return 'pending';
    }
  })();

  return (
    <span className={`chat-workflow-node-badge chat-workflow-node-badge--${variant} selectable-text`} onMouseDown={(e) => e.stopPropagation()}>
      <span className="chat-workflow-node-badge__dot" />
      <span>{CHAT_WORKFLOW_NODE_LABEL[node.nodeType]}</span>
      <span>·</span>
      <span>{CHAT_NODE_STATUS_LABEL[node.status]}</span>
      {node.latencyMs !== undefined && <span>· {node.latencyMs}ms</span>}
    </span>
  );
};
