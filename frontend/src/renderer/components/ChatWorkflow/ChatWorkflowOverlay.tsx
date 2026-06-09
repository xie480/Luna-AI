import React, { useMemo } from 'react';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { useSessionStore } from '../../stores/sessionStore';
import type { ChatCitationProjection } from '../../../shared/types';
import type { ChatWorkflowMessageMetadata } from '../../types/chatWorkflow';
import { ChatWorkflowStepBar } from './ChatWorkflowStepBar';
import { ChatWorkflowMetadataPanel } from './ChatWorkflowMetadataPanel';
import './ChatWorkflow.css';

/**
 * Chat Workflow 叠加层组件。
 * 做什么：把步骤条与 assistant 元数据卡片统一挂载在聊天主视图上。
 * 为什么这样做：当前主界面没有持久化消息列表，需要以独立覆盖层补充 Phase 8.5 的最小 workflow 可视反馈。
 * 输入输出：输入会话消息与 workflow store，输出步骤条和元数据面板。
 * 边界条件：无活跃计划时只显示步骤条空态或不显示元数据面板。
 * 异常行为：无。
 */
export const ChatWorkflowOverlay: React.FC = () => {
  const activePlan = useChatWorkflowStore((state) => state.activePlan);
  const getMessageMetadata = useChatWorkflowStore((state) => state.getMessageMetadata);
  const currentSessionId = useSessionStore((state) => state.currentSessionId);
  const messages = useSessionStore((state) => (state.currentSessionId ? state.messages[state.currentSessionId] || [] : []));

  /**
   * 读取当前轮 assistant 消息及其元数据。
   * 做什么：优先关联活跃计划的 assistantMessageId，避免拿到历史消息的元数据。
   * 为什么这样做：workflow 元数据必须与当前正在执行或刚完成的回复稳定绑定。
   * 输入输出：输入当前会话消息数组，输出面板可消费的结构化元数据。
   * 边界条件：消息 metadata 仍是宽松对象时，必须逐字段显式校验后再使用。
   * 异常行为：无。
   */
  const metadata = useMemo<ChatWorkflowMessageMetadata | null>(() => {
    if (!currentSessionId || !activePlan) {
      return null;
    }
    const targetAssistantMessage =
      messages.find((message) => message.messageId === activePlan.assistantMessageId) ||
      [...messages].reverse().find((message) => message.role === 'assistant');
    if (!targetAssistantMessage) {
      return null;
    }

    const rawMetadata = (targetAssistantMessage.metadata || {}) as Record<string, unknown>;
    const interactionId =
      (typeof rawMetadata.interactionId === 'string' ? rawMetadata.interactionId : undefined) ||
      activePlan.interactionId;
    const assistantMessageId =
      (typeof rawMetadata.assistantMessageId === 'string' ? rawMetadata.assistantMessageId : undefined) ||
      targetAssistantMessage.messageId;
    const baseMetadata = getMessageMetadata(interactionId, assistantMessageId);
    if (!baseMetadata) {
      return null;
    }

    const citations = Array.isArray(rawMetadata.citations)
      ? (rawMetadata.citations as ChatCitationProjection[])
      : baseMetadata.citations;

    return {
      ...baseMetadata,
      traceId:
        baseMetadata.traceId || (typeof rawMetadata.traceId === 'string' ? rawMetadata.traceId : activePlan.traceId),
      planPresetId:
        (typeof rawMetadata.planPresetId === 'string' ? rawMetadata.planPresetId : undefined) || baseMetadata.planPresetId,
      citations,
    };
  }, [activePlan, currentSessionId, getMessageMetadata, messages]);

  if (!activePlan) {
    return null;
  }

  return (
    <div className="chat-workflow-stack">
      <ChatWorkflowStepBar />
      <ChatWorkflowMetadataPanel metadata={metadata} />
    </div>
  );
};
