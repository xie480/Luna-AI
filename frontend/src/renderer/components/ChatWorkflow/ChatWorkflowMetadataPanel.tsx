import React from 'react';
import {
  CHAT_PLAN_PRESET,
  CHAT_WORKFLOW_NODE_LABEL,
  CHAT_WORKFLOW_NODE_TYPE,
} from '../../../shared/enum';
import type { ChatWorkflowMessageMetadata } from '../../types/chatWorkflow';
import { ChatWorkflowNodeBadge } from './ChatWorkflowNodeBadge';
import { ChatWorkflowConditionItem } from './ChatWorkflowConditionItem';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import './ChatWorkflow.css';

/**
 * Assistant 元数据面板组件。
 * 做什么：展示本轮回复关联的 plan、条件节点进入结果、引用数量与节点摘要。
 * 为什么这样做：结构化元数据应与消息正文分离，避免污染复制内容和 Markdown 渲染。
 * 输入输出：输入元数据对象，输出默认折叠的元数据卡片。
 * 边界条件：metadata 为空时展示空态，不参与任何调度。
 * 异常行为：无。
 */
export const ChatWorkflowMetadataPanel: React.FC<{
  metadata: ChatWorkflowMessageMetadata | null;
}> = ({ metadata }) => {
  const expanded = useChatWorkflowStore(
    (state) => (metadata ? state.metadataPanelExpandedByMessageId[metadata.assistantMessageId] ?? false : false)
  );
  const latestConditionResults = useChatWorkflowStore((state) => state.latestConditionResults);
  const toggleMetadataPanelExpanded = useChatWorkflowStore((state) => state.toggleMetadataPanelExpanded);

  if (!metadata) {
    return (
      <div className="chat-workflow-metadata-panel">
        <div className="chat-workflow-metadata-panel__empty">当前回复尚未收到 workflow 元数据。</div>
      </div>
    );
  }

  const longTermReason = latestConditionResults[
    `${metadata.interactionId}:${CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG}`
  ]?.reason;
  const knowledgeReason = latestConditionResults[
    `${metadata.interactionId}:${CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG}`
  ]?.reason;

  return (
    <div className="chat-workflow-metadata-panel">
      <div className="chat-workflow-metadata-panel__header">
        <div>
          <div className="chat-workflow-metadata-panel__title">本轮回复元数据</div>
          <div className="chat-workflow-metadata-panel__subtitle">
            计划预设：{metadata.planPresetId || CHAT_PLAN_PRESET.DAILY_CHAT_DEFAULT}
          </div>
        </div>
        <button
          type="button"
          className="chat-workflow-metadata-panel__toggle"
          onClick={() => toggleMetadataPanelExpanded(metadata.assistantMessageId)}
        >
          {expanded ? '收起详情' : '展开详情'}
        </button>
      </div>

      {expanded && (
        <div className="chat-workflow-metadata-panel__body">
          <div className="chat-workflow-metadata-panel__grid">
            <div className="chat-workflow-metadata-panel__item">
              <div className="chat-workflow-metadata-panel__label">Trace ID</div>
              <div className="chat-workflow-metadata-panel__value">{metadata.traceId || '等待同步'}</div>
            </div>
            <div className="chat-workflow-metadata-panel__item">
              <div className="chat-workflow-metadata-panel__label">Interaction ID</div>
              <div className="chat-workflow-metadata-panel__value">{metadata.interactionId}</div>
            </div>
            <div className="chat-workflow-metadata-panel__item">
              <div className="chat-workflow-metadata-panel__label">当前节点</div>
              <div className="chat-workflow-metadata-panel__value">
                {metadata.activeNodeType ? CHAT_WORKFLOW_NODE_LABEL[metadata.activeNodeType] : '等待节点开始'}
              </div>
            </div>
            <div className="chat-workflow-metadata-panel__item">
              <div className="chat-workflow-metadata-panel__label">引用数量</div>
              <div className="chat-workflow-metadata-panel__value">{metadata.citations.length}</div>
            </div>
          </div>

          <div className="chat-workflow-metadata-panel__conditions">
            <ChatWorkflowConditionItem
              interactionId={metadata.interactionId}
              nodeType={CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG}
              conditionEntered={metadata.enteredLongTermMemoryRag}
              reason={longTermReason}
            />
            <ChatWorkflowConditionItem
              interactionId={metadata.interactionId}
              nodeType={CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG}
              conditionEntered={metadata.enteredKnowledgeRag}
              reason={knowledgeReason}
            />
          </div>

          <div className="chat-workflow-metadata-panel__nodes">
            <div className="chat-workflow-metadata-panel__label">节点摘要</div>
            <div className="chat-workflow-metadata-panel__nodes-row">
              {metadata.nodeTimelineSummary.map((node) => (
                <ChatWorkflowNodeBadge key={node.nodeType} node={node} />
              ))}
            </div>
          </div>

          {metadata.postprocessSummary && (
            <div className="chat-workflow-metadata-panel__item">
              <div className="chat-workflow-metadata-panel__label">后处理备注</div>
              <div className="chat-workflow-metadata-panel__value">{metadata.postprocessSummary}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
