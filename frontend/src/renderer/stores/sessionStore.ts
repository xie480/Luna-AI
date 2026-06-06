/**
 * Luna AI 会话状态管理
 * 使用 Zustand 管理全局会话状态，严格遵循 Go Runtime 为唯一状态权威的原则
 * 注意：前端状态仅为 Go 推送状态的投影，禁止乐观更新
 */
import { create } from 'zustand';
import { InteractionQA } from '../../shared/types';

/**
 * 聊天消息结构
 * 与 Go Runtime 的 WSMessage 结构对齐
 */
export interface ChatMessage {
  messageId: string;
  sessionId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  contentType: 'text' | 'markdown' | 'audio' | 'mixed';
  content: string;
  timestamp: number;
  status: 'sending' | 'streaming' | 'completed' | 'error'; // 由 Go 控制
  metadata?: Record<string, unknown>;
}

/**
 * 任务节点状态（Go 调度的最小单元投影）
 */
export interface TaskNodeState {
  nodeId: string;
  name: string;
  description: string;
  status: 'pending' | 'running' | 'waiting_user_auth' | 'completed' | 'failed' | 'retrying';
  progress: number;
  errorMsg?: string;
  toolCall?: {
    toolName: string;
    params: string;
  };
}

/**
 * 工作流计划快照
 */
export interface PlanSnapshot {
  planId: string;
  goal: string;
  createdAt: number;
  nodes: TaskNodeState[];
  edges: { source: string; target: string }[];
  currentActiveNodeIds: string[];
}

/**
 * 记忆快照
 */
export interface MemorySnapshot {
  persona: string[];
  shortTerm: string[];
  longTermFacts: string[];
}

/**
 * 会话状态切片
 */
interface SessionState {
  // 当前会话 ID
  currentSessionId: string | null;
  // 消息记录，Key 为 sessionId
  messages: Record<string, ChatMessage[]>;
  // 近期记忆（最后 3 轮 Q&A，用于右上角面板展示）
  recentQA: InteractionQA[];
  // 当前活跃的任务计划
  activePlan: PlanSnapshot | null;
  // 记忆快照
  memory: MemorySnapshot | null;

  // Actions - 状态更新操作
  setSessionId: (id: string) => void;
  appendMessage: (sessionId: string, msg: ChatMessage) => void;
  updateMessageChunk: (sessionId: string, msgId: string, chunk: string) => void;
  updateMessageStatus: (sessionId: string, msgId: string, status: ChatMessage['status']) => void;
  updateMessageMetadata: (sessionId: string, msgId: string, metadata: Record<string, unknown>) => void;
  setRecentQA: (qaList: InteractionQA[]) => void;
  addRecentQA: (qa: InteractionQA) => void;
  updatePlan: (plan: PlanSnapshot) => void;
  updateNodeStatus: (nodeId: string, status: TaskNodeState['status'], progress?: number) => void;
  updateMemory: (memory: MemorySnapshot) => void;
  clearMessages: (sessionId: string) => void;
  /** 清除所有处于 waiting 状态（sending/streaming）的消息，释放输入框锁定 */
  clearAllWaitingStates: () => void;
}

/**
 * 创建会话状态 Store
 * 所有状态更新必须基于 Go 推送的事件，禁止前端自行推断状态
 */
export const useSessionStore = create<SessionState>((set) => ({
  currentSessionId: null,
  messages: {},
  recentQA: [],
  activePlan: null,
  memory: null,

  // 设置当前会话 ID
  setSessionId: (id) => set({ currentSessionId: id }),

  // 追加新消息
  appendMessage: (sessionId, msg) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [...(state.messages[sessionId] || []), msg],
      },
    })),

  // 更新消息内容（流式输出时使用）
  updateMessageChunk: (sessionId, msgId, chunk) =>
    set((state) => {
      const sessionMessages = state.messages[sessionId] || [];
      const msgIndex = sessionMessages.findIndex((m) => m.messageId === msgId);
      
      if (msgIndex === -1) {
        const newMsg: ChatMessage = {
          messageId: msgId,
          sessionId,
          role: 'assistant',
          contentType: 'text',
          content: chunk,
          timestamp: Date.now(),
          status: 'streaming',
        };
        return {
          messages: {
            ...state.messages,
            [sessionId]: [...sessionMessages, newMsg],
          },
        };
      }

      const updatedMessages = [...sessionMessages];
      updatedMessages[msgIndex] = {
        ...updatedMessages[msgIndex],
        content: updatedMessages[msgIndex].content + chunk,
        status: 'streaming',
      };

      return {
        messages: {
          ...state.messages,
          [sessionId]: updatedMessages,
        },
      };
    }),

  // 更新消息元数据
  updateMessageMetadata: (sessionId, msgId, metadata) =>
    set((state) => {
      const sessionMessages = state.messages[sessionId] || [];
      const msgIndex = sessionMessages.findIndex((m) => m.messageId === msgId);
      
      if (msgIndex === -1) return state;

      const updatedMessages = [...sessionMessages];
      updatedMessages[msgIndex] = {
        ...updatedMessages[msgIndex],
        metadata: {
          ...updatedMessages[msgIndex].metadata,
          ...metadata
        }
      };

      return {
        messages: {
          ...state.messages,
          [sessionId]: updatedMessages,
        },
      };
    }),

  // 更新消息状态
  updateMessageStatus: (sessionId, msgId, status) =>
    set((state) => {
      const sessionMessages = state.messages[sessionId] || [];
      const msgIndex = sessionMessages.findIndex((m) => m.messageId === msgId);
      
      if (msgIndex === -1) {
        const newMsg: ChatMessage = {
          messageId: msgId,
          sessionId,
          role: 'assistant',
          contentType: 'text',
          content: '',
          timestamp: Date.now(),
          status,
        };
        return {
          messages: {
            ...state.messages,
            [sessionId]: [...sessionMessages, newMsg],
          },
        };
      }

      const updatedMessages = [...sessionMessages];
      updatedMessages[msgIndex] = {
        ...updatedMessages[msgIndex],
        status,
      };

      return {
        messages: {
          ...state.messages,
          [sessionId]: updatedMessages,
        },
      };
    }),

  // 设置近期记忆列表（用于初始加载时从 Go 端获取）
  // 根据 msgId 去重，防止后端返回数据中存在重复条目导致 React key 重复警告
  setRecentQA: (qaList) =>
    set(() => {
      const seen = new Set<string>();
      const deduped = qaList.filter((qa) => {
        if (seen.has(qa.msgId)) return false;
        seen.add(qa.msgId);
        return true;
      });
      return { recentQA: deduped };
    }),

  // 追加单条近期记忆（保持最多 3 条）
  // 新条目追加到末尾，超出 3 条时移除最旧的一条
  // 根据 msgId 去重，防止同一 msgId 多次添加导致 React key 重复警告
  addRecentQA: (qa) =>
    set((state) => {
      // 先移除已有的同 msgId 条目（去重），再追加新条目
      const dedupedList = state.recentQA.filter((item) => item.msgId !== qa.msgId);
      const newList = [...dedupedList, qa];
      if (newList.length > 3) {
        newList.shift();
      }
      return { recentQA: newList };
    }),

  // 更新任务计划快照
  updatePlan: (plan) => set({ activePlan: plan }),

  // 更新任务节点状态
  updateNodeStatus: (nodeId, status, progress) =>
    set((state) => {
      if (!state.activePlan) return state;

      const updatedNodes = state.activePlan.nodes.map((node) =>
        node.nodeId === nodeId
          ? { ...node, status, progress: progress ?? node.progress }
          : node
      );

      return {
        activePlan: {
          ...state.activePlan,
          nodes: updatedNodes,
        },
      };
    }),

  // 更新记忆快照
  updateMemory: (memory) => set({ memory }),

  // 清空指定会话的消息
  clearMessages: (sessionId) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [],
      },
    })),

  // 清除所有 waiting 状态（sending/streaming）的消息
  // 在加载动画结束后调用，确保输入框不被陈旧状态锁定
  clearAllWaitingStates: () =>
    set((state) => {
      const updated: Record<string, ChatMessage[]> = {};
      for (const [sessionId, msgs] of Object.entries(state.messages)) {
        updated[sessionId] = msgs.map((m) =>
          m.status === 'sending' || m.status === 'streaming'
            ? { ...m, status: 'error' as const }
            : m
        );
      }
      return { messages: updated };
    }),
}));
