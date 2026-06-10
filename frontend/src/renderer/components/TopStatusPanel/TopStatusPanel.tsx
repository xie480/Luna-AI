import React, { useEffect } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { useVisualStatusQueue, VisualStateItem } from '../../stores/visualStatusQueueStore';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import { CHAT_WORKFLOW_NODE_TYPE, CHAT_NODE_STATUS } from '../../../shared/enum';
import { OrbitalArcContainer } from './OrbitalArcContainer';
import './TopStatusPanel.css';

/**
 * 依据全息空间美学，将后端节点映射为极具科技感的前端状态描述
 */
const mapNodeToVisualState = (nodeType: string, status: string): Partial<VisualStateItem> | null => {
  if (status === CHAT_NODE_STATUS.RUNNING || status === CHAT_NODE_STATUS.SUCCEEDED) {
    switch (nodeType) {
      case CHAT_WORKFLOW_NODE_TYPE.INPUT_RECONSTRUCTION:
        return { stage: 'INPUT_RECONSTRUCTION', text: '正在重构意图模型...', colorTheme: 'purple' };
      case CHAT_WORKFLOW_NODE_TYPE.SESSION_CONTEXT_LOAD:
        return { stage: 'SESSION_CONTEXT_LOAD', text: '同步会话上下文...', colorTheme: 'blue' };
      case CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_RAG:
        return { stage: 'LONG_TERM_MEMORY_RAG', text: '下潜长期记忆层...', colorTheme: 'cyan' };
      case CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_INJECTION:
        return { stage: 'USER_PROFILE_INJECTION', text: '匹配用户潜意识画像...', colorTheme: 'purple' };
      case CHAT_WORKFLOW_NODE_TYPE.KNOWLEDGE_RAG:
        return { stage: 'KNOWLEDGE_RAG', text: '链接外部知识库矩阵...', colorTheme: 'blue' };
      case CHAT_WORKFLOW_NODE_TYPE.CONTEXT_GOVERNANCE:
        return { stage: 'CONTEXT_GOVERNANCE', text: '压缩高维冗余数据...', colorTheme: 'purple' };
      case CHAT_WORKFLOW_NODE_TYPE.PROMPT_ASSEMBLY:
        return { stage: 'PROMPT_ASSEMBLY', text: '正在装配思维流...', colorTheme: 'cyan' };
      case CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM:
        return { stage: 'MAIN_CHAT_LLM', text: '云端神经计算供能中...', colorTheme: 'cyan' };
      case CHAT_WORKFLOW_NODE_TYPE.RESPONSE_PERSISTENCE:
        return { stage: 'RESPONSE_PERSISTENCE', text: '持久化记忆锚点...', colorTheme: 'cyan' };
      case CHAT_WORKFLOW_NODE_TYPE.LONG_TERM_MEMORY_COMPRESSION:
        return { stage: 'LONG_TERM_MEMORY_COMPRESSION', text: '深层记忆快照压缩...', colorTheme: 'blue' };
      case CHAT_WORKFLOW_NODE_TYPE.USER_PROFILE_EXTRACTION:
        return { stage: 'USER_PROFILE_EXTRACTION', text: '提炼画像潜特征...', colorTheme: 'purple' };
      case CHAT_WORKFLOW_NODE_TYPE.POSTPROCESS_COMMIT:
        return { stage: 'POSTPROCESS_COMMIT', text: '同步后处理事务...', colorTheme: 'cyan' };
      case CHAT_WORKFLOW_NODE_TYPE.FINALIZE:
        return { stage: 'FINALIZE', text: '工作流坍缩完成...', colorTheme: 'cyan' };
      default:
        return { stage: nodeType, text: '解析信号参数...', colorTheme: 'blue' };
    }
  } else if (status === CHAT_NODE_STATUS.FAILED || status === CHAT_NODE_STATUS.DEGRADED) {
    return { stage: nodeType, text: '警告：神经链路遭遇异常扰动', colorTheme: 'red', state: 'ERROR' };
  }
  return null;
};

export const TopStatusPanel: React.FC = () => {
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const enqueue = useVisualStatusQueue(state => state.enqueue);
  const { currentVisualState, queue } = useVisualStatusQueue();
  const activePlan = useChatWorkflowStore(state => state.activePlan);
  const nodesByInteractionId = useChatWorkflowStore(state => state.nodesByInteractionId);

  useEffect(() => {
    if (!activePlan) return;

    const interactionNodes = nodesByInteractionId[activePlan.interactionId];
    if (!interactionNodes || interactionNodes.length === 0) {
      enqueue({
        id: `plan-started-${activePlan.interactionId}-${activePlan.startedAtMs}`,
        stage: 'PLAN_STARTED',
        state: 'RUNNING',
        text: '建立深空连接...',
        colorTheme: 'blue',
      });
      return;
    }

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
      colorTheme: visualMapping.colorTheme as VisualStateItem['colorTheme'],
      isTerminal:
        latestNode.nodeType === CHAT_WORKFLOW_NODE_TYPE.MAIN_CHAT_LLM &&
        latestNode.status === CHAT_NODE_STATUS.SUCCEEDED,
    });
  }, [activePlan, nodesByInteractionId, enqueue]);

  useEffect(() => {
    if (connectionStatus === 'disconnected') {
      enqueue({
        id: `sys-disconnected-${Date.now()}`,
        stage: 'SYSTEM',
        state: 'ERROR',
        text: '空间站链接中断，尝试重连...',
        colorTheme: 'red',
      });
    } else if (connectionStatus === 'connected') {
      enqueue({
        id: `sys-connected-${Date.now()}`,
        stage: 'SYSTEM',
        state: 'COMPLETED',
        text: '量子网络已同步',
        colorTheme: 'cyan',
        isTerminal: true, 
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
