import React, { useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { useVisualStatusQueue, VisualStateItem } from '../../stores/visualStatusQueueStore';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { CHAT_WORKFLOW_NODE_TYPE, CHAT_NODE_STATUS } from '../../../shared/enum';
import { OrbitalArcContainer } from './OrbitalArcContainer';
import './TopStatusPanel.css';

/**
 * 根据工作流节点类型和状态映射到全息引力弧的视觉项。
 * 执行阶段（RUNNING/SUCCEEDED）映射为不同主题色的流转态；
 * 异常阶段（FAILED/DEGRADED）映射为红色错误态。
 * 输入输出：输入后端节点类型与状态，输出视觉队列项（部分字段）或 null。
 * 边界条件：未映射的节点类型静默忽略。
 */
const mapNodeToVisualState = (nodeType: string, status: string): Partial<VisualStateItem> | null => {
  if (status === CHAT_NODE_STATUS.RUNNING || status === CHAT_NODE_STATUS.SUCCEEDED) {
    switch (nodeType) {
      case CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION:
        return { stage: 'INPUT_RECONSTRUCTION', text: '正在理解意图...', colorTheme: 'purple' as const };
      case CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD:
        return { stage: 'SESSION_CONTEXT_LOAD', text: '正在加载会话上下文...', colorTheme: 'blue' as const };
      case CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG:
        return { stage: 'LONG_TERM_MEMORY_RAG', text: '正在检索长期记忆...', colorTheme: 'blue' as const };
      case CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION:
        return { stage: 'USER_PROFILE_INJECTION', text: '正在注入用户画像...', colorTheme: 'purple' as const };
      case CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG:
        return { stage: 'KNOWLEDGE_RAG', text: '正在检索知识库...', colorTheme: 'blue' as const };
      case CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE:
        return { stage: 'CONTEXT_GOVERNANCE', text: '正在治理上下文...', colorTheme: 'purple' as const };
      case CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY:
        return { stage: 'PROMPT_ASSEMBLY', text: '正在组装提示词...', colorTheme: 'cyan' as const };
      case CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM:
        return { stage: 'MAIN_CHAT_LLM', text: '正在思考...', colorTheme: 'cyan' as const };
      case CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE:
        return { stage: 'RESPONSE_PERSISTENCE', text: '正在持久化回复...', colorTheme: 'cyan' as const };
      case CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_COMPRESSION:
        return { stage: 'LONG_TERM_MEMORY_COMPRESSION', text: '正在压缩长期记忆...', colorTheme: 'blue' as const };
      case CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_EXTRACTION:
        return { stage: 'USER_PROFILE_EXTRACTION', text: '正在提取用户画像...', colorTheme: 'purple' as const };
      case CHAT_WORKFLOW_NODE_TYPE.POSTPROCESS_COMMIT:
        return { stage: 'POSTPROCESS_COMMIT', text: '正在后处理提交...', colorTheme: 'cyan' as const };
      case CHAT_WORKFLOW_NODE_TYPE.FINALIZE:
        return { stage: 'FINALIZE', text: '正在收尾...', colorTheme: 'cyan' as const };
      default:
        return { stage: nodeType, text: '正在处理...', colorTheme: 'blue' as const };
    }
  } else if (status === CHAT_NODE_STATUS.FAILED || status === CHAT_NODE_STATUS.DEGRADED) {
    return { stage: nodeType, text: '处理出现异常', colorTheme: 'red' as const, state: 'ERROR' as const };
  }
  return null;
};

/**
 * 全局状态面板组件（全息引力弧）。
 * 做什么：监听后端工作流节点状态变化与系统连接状态，通过 VisualStatusQueue 驱动视觉效果。
 * 为什么这样做：全息引力弧需要根据节点流转展现星轨、主星和柔性文字的联动动效。
 * 输入输出：无直接输入；输出为 OrbitalArcContainer 的视觉状态。
 * 边界条件：无 activePlan 或节点列表为空时退回空闲态。
 * 异常行为：连接断开时强行推送错误态。
 */
export const TopStatusPanel: React.FC = () => {
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const enqueue = useVisualStatusQueue(state => state.enqueue);
  const { currentVisualState, queue } = useVisualStatusQueue();
  const activePlan = useChatWorkflowStore(state => state.activePlan);
  const nodesByInteractionId = useChatWorkflowStore(state => state.nodesByInteractionId);

  /**
   * 监听 activePlan 的变化，将当前活跃节点转化为视觉项推入队列。
   * 依赖 activePlan.activeNodeType 识别当前执行阶段。
   */
  useEffect(() => {
    if (!activePlan) {
      // plan 为空（未开始或已完成），不做处理（由系统连接状态兜底空闲态）
      return;
    }

    const interactionNodes = nodesByInteractionId[activePlan.interactionId];
    if (!interactionNodes || interactionNodes.length === 0) {
      // 刚启动 plan 但尚无节点事件时，根据 plan 状态给出等待提示
      enqueue({
        id: `plan-started-${activePlan.interactionId}-${activePlan.startedAtMs}`,
        stage: 'PLAN_STARTED',
        state: 'RUNNING',
        text: '开始处理...',
        colorTheme: 'blue',
      });
      return;
    }

    // 取最后更新的节点（即最近的节点状态变化）
    const sortedNodes = [...interactionNodes].sort(
      (a, b) => (b.updatedAtMs || 0) - (a.updatedAtMs || 0)
    );
    const latestNode = sortedNodes[0];

    if (!latestNode) return;

    const visualMapping = mapNodeToVisualState(latestNode.nodeType, latestNode.status);
    if (!visualMapping || !visualMapping.text) return;

    enqueue({
      id: `${activePlan.interactionId}-${latestNode.nodeType}-${latestNode.status}-${latestNode.updatedAtMs}`,
      stage: visualMapping.stage || latestNode.nodeType,
      state: visualMapping.state || (
        latestNode.status === CHAT_NODE_STATUS.SUCCEEDED
          ? 'COMPLETED'
          : 'RUNNING'
      ),
      text: visualMapping.text,
      colorTheme: visualMapping.colorTheme,
      // MAIN_CHAT_LLM 节点完成视为终端节点，驻留后清理
      isTerminal:
        latestNode.nodeType === CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM &&
        latestNode.status === CHAT_NODE_STATUS.SUCCEEDED,
    });
  }, [activePlan, nodesByInteractionId, enqueue]);

  /**
   * 被动监听系统连接状态变化，连接断开时推送错误态。
   */
  useEffect(() => {
    if (connectionStatus === 'disconnected') {
      enqueue({
        id: `sys-disconnected-${Date.now()}`,
        stage: 'SYSTEM',
        state: 'ERROR',
        text: '系统断开连接，正在重试...',
        colorTheme: 'red',
      });
    } else if (connectionStatus === 'connected') {
      enqueue({
        id: `sys-connected-${Date.now()}`,
        stage: 'SYSTEM',
        state: 'COMPLETED',
        text: '系统已连接',
        colorTheme: 'cyan',
        isTerminal: true, // 驻留后清理
      });
    }
  }, [connectionStatus, enqueue]);

  return (
    <div className="top-status-panel">
      <OrbitalArcContainer
        currentVisualState={currentVisualState}
        queueLength={queue.length}
      />
    </div>
  );
};
