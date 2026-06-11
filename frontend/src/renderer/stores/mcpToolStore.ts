/**
 * MCP 工具执行状态 Store。
 *
 * 做什么：管理 MCP 工具执行状态的前端投影。
 * 为什么这样做：MCP 状态需要跨组件共享（状态指示器、结果气泡、调试面板），
 *             因此放在 Zustand 全局状态中而不是组件局部状态。
 * 边界条件：
 *   - 每轮新对话开始时必须重置为 null。
 *   - 后端可能推送多个状态事件，Store 需要做合并更新而非覆盖。
 * 异常行为：
 *   - 后端推送的事件顺序可能与实际执行顺序不一致（网络乱序），
 *     前端依赖 sequence 字段做防乱序处理。
 */
import { create } from 'zustand';
import type { MCPToolStatusProjection } from '../../shared/types';

/**
 * MCP 工具状态 Store 接口。
 */
interface MCPToolState {
  /** MCP 工具执行状态投影。 */
  mcpToolStatus: MCPToolStatusProjection | null;
  /** 工具调用是否完成（用于控制结果气泡的渲染时机）。 */
  toolCallCompleted: boolean;
  /** 上次 MCP 状态事件的 sequence 值，用于防乱序。 */
  lastMCPStatusSequence: number;

  /** 设置或合并更新 MCP 工具状态。 */
  setMCPToolStatus: (statusUpdate: Partial<MCPToolStatusProjection>) => void;
  /** 重置 MCP 工具状态为 null。 */
  resetMCPToolStatus: () => void;
  /** 设置工具调用完成状态。 */
  setToolCallCompleted: (completed: boolean) => void;
  /** 设置上次 MCP 状态事件的 sequence 值。 */
  setLastMCPStatusSequence: (sequence: number) => void;
}

/**
 * 创建空的 MCP 工具状态默认值。
 * 做什么：当首次收到更新时，用默认值填充缺失字段。
 * 为什么这样做：避免组件中频繁判空。
 */
function createEmptyMCPToolStatus(): MCPToolStatusProjection {
  return {
    enteredByCondition: false,
    conditionReason: '',
  };
}

/**
 * MCP 工具状态 Store。
 */
export const useMCPToolStore = create<MCPToolState>((set) => ({
  mcpToolStatus: null,
  toolCallCompleted: false,
  lastMCPStatusSequence: -1,

  setMCPToolStatus: (statusUpdate) =>
    set((state) => ({
      mcpToolStatus: state.mcpToolStatus
        ? { ...state.mcpToolStatus, ...statusUpdate }
        : { ...createEmptyMCPToolStatus(), ...statusUpdate },
    })),

  resetMCPToolStatus: () =>
    set({ mcpToolStatus: null, toolCallCompleted: false, lastMCPStatusSequence: -1 }),

  setToolCallCompleted: (completed) =>
    set({ toolCallCompleted: completed }),

  setLastMCPStatusSequence: (sequence) =>
    set({ lastMCPStatusSequence: sequence }),
}));
