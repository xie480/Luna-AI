import React, { useMemo } from 'react';
import { CHAT_NODE_STATUS_LABEL, CHAT_WORKFLOW_NODE_LABEL, CHAT_WORKFLOW_NODE_TYPE } from '../../../shared/enum';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { useSystemStore } from '../../stores/systemStore';
import { useTelemetryStore } from '../../stores/telemetryStore';
import { ChatWorkflowConditionItem } from './ChatWorkflowConditionItem';
import { ChatWorkflowNodeBadge } from './ChatWorkflowNodeBadge';
import './ChatWorkflow.css';

/**
 * 当前执行步骤条组件。
 * 做什么：在聊天输入框上方展示当前执行节点、近期节点摘要和条件节点状态。
 * 为什么这样做：Phase 8.5 需要最小改造承接节点化主链路，同时保持现有流式体验不被重写。
 * 输入输出：输入 workflow store 投影状态，输出轻量悬浮步骤条。
 * 边界条件：无活跃计划时不渲染；条件节点只展示后端已推送的结果。
 * 异常行为：无。
 */
export const ChatWorkflowStepBar: React.FC = () => {
  const activePlan = useChatWorkflowStore((state) => state.activePlan);
  const isStepBarVisible = useChatWorkflowStore((state) => state.isStepBarVisible);
  const nodesByInteractionId = useChatWorkflowStore((state) => state.nodesByInteractionId);
  const latestConditionResults = useChatWorkflowStore((state) => state.latestConditionResults);
  const setDiagnosticOpen = useSystemStore((state) => state.setDiagnosticOpen);
  const setActiveDebugTab = useTelemetryStore((state) => state.setActiveDebugTab);

  /**
   * 基于当前 interaction 读取节点列表。
   * 做什么：为步骤条、条件区和摘要徽标提供统一的数据来源。
   * 为什么这样做：workflow 视图必须完全依赖后端投影，不能在组件层二次推断节点。
   * 输入输出：输入 activePlan，输出当前 interaction 的节点数组。
   * 边界条件：无 activePlan 时返回空数组。
   * 异常行为：无。
   */
  const nodes = useMemo(() => {
    if (!activePlan) {
      return [];
    }
    return nodesByInteractionId[activePlan.interactionId] || [];
  }, [activePlan, nodesByInteractionId]);

  /**
   * 解析当前主状态文案。
   * 做什么：根据活跃节点和后处理阶段生成面向用户的步骤说明。
   * 为什么这样做：文档要求展示“正在理解输入 / 正在生成回复”等轻量当前步骤文案。
   * 输入输出：输入 activePlan 与节点列表，输出标题与状态文本。
   * 边界条件：后处理进行中时优先显示后台整理语义。
   * 异常行为：无。
   */
  const currentStep = useMemo(() => {
    if (!activePlan) {
      return null;
    }
    if (activePlan.isPostprocessing) {
      return {
        title: '正在后台整理记忆',
        status: '后处理进行中',
      };
    }
    const currentNode = nodes.find((node) => node.nodeType === activePlan.activeNodeType) || nodes[nodes.length - 1];
    if (!currentNode) {
      return {
        title: '正在准备本轮回复',
        status: '等待节点开始',
      };
    }
    const titleMap: Record<string, string> = {
      [CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION]: '正在理解你的输入',
      [CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD]: '正在整理会话上下文',
      [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG]: '正在读取相关长期记忆',
      [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION]: '正在注入用户画像',
      [CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG]: '正在检索知识库证据',
      [CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE]: '正在组织回复上下文',
      [CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY]: '正在装配回复提示词',
      [CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM]: '正在生成回复',
      [CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE]: '正在保存本轮对话',
      [CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_COMPRESSION]: '正在后台整理记忆',
      [CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_EXTRACTION]: '正在提取用户画像',
      [CHAT_WORKFLOW_NODE_TYPE.POSTPROCESS_COMMIT]: '正在提交后台整理结果',
      [CHAT_WORKFLOW_NODE_TYPE.ERROR_RECOVERY]: '正在处理异常并恢复',
      [CHAT_WORKFLOW_NODE_TYPE.FINALIZE]: '正在完成本轮收尾',
    };
    return {
      title: titleMap[currentNode.nodeType] || `正在处理：${CHAT_WORKFLOW_NODE_LABEL[currentNode.nodeType]}`,
      status: CHAT_NODE_STATUS_LABEL[currentNode.status],
    };
  }, [activePlan, nodes]);

  /**
   * 条件节点展示列表。
   * 做什么：按固定顺序展示长期记忆、用户画像、知识库三个条件节点的判断结果。
   * 为什么这样做：这些节点是 Phase 8.5 文档明确要求展示的关键条件路由。
   * 输入输出：输入条件结果字典，输出可渲染数组。
   * 边界条件：未收到条件事件时保留为空，不做前端猜测。
   * 异常行为：无。
   */
  const conditionItems = useMemo(() => {
    if (!activePlan) {
      return [];
    }
    return [
      CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG,
      CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG,
    ].map((nodeType) => ({
      nodeType,
      result: latestConditionResults[`${activePlan.interactionId}:${nodeType}`],
    }));
  }, [activePlan, latestConditionResults]);

  if (!isStepBarVisible || !activePlan || !currentStep) {
    return null;
  }

  return (
    <div className="chat-workflow-stepbar">
      <div className="chat-workflow-stepbar__header">
        <div className="chat-workflow-stepbar__title-group">
          <div className="chat-workflow-stepbar__eyebrow">Daily Chat Workflow</div>
          <div className="chat-workflow-stepbar__title">{currentStep.title}</div>
          <div className="chat-workflow-stepbar__status">
            <span className="chat-workflow-node-badge chat-workflow-node-badge--running">
              <span className="chat-workflow-node-badge__dot" />
              <span>{currentStep.status}</span>
            </span>
            {activePlan.degradedNodeCount > 0 && (
              <span className="chat-workflow-node-badge chat-workflow-node-badge--degraded">
                <span className="chat-workflow-node-badge__dot" />
                <span>存在降级节点</span>
              </span>
            )}
          </div>
        </div>
        <div className="chat-workflow-stepbar__actions">
          <button
            type="button"
            className="chat-workflow-action-btn"
            onClick={() => {
              setDiagnosticOpen(true);
              setActiveDebugTab('workflow');
            }}
          >
            查看时间线
          </button>
        </div>
      </div>

      <div className="chat-workflow-stepbar__summary">
        {nodes.length === 0 ? (
          <div className="chat-workflow-stepbar__empty">等待后端推送节点事件…</div>
        ) : (
          nodes.slice(-4).map((node) => <ChatWorkflowNodeBadge key={node.nodeType} node={node} />)
        )}
      </div>

      <div className="chat-workflow-stepbar__conditions">
        {conditionItems.map(({ nodeType, result }) => (
          <ChatWorkflowConditionItem
            key={nodeType}
            interactionId={activePlan.interactionId}
            nodeType={nodeType}
            conditionEntered={result?.conditionEntered}
            reason={result?.reason}
          />
        ))}
      </div>
    </div>
  );
};
