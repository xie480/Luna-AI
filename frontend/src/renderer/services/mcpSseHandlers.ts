/**
 * MCP SSE 事件处理器。
 *
 * 做什么：处理后端推送的 MCP 工具执行相关 SSE 事件。
 *         包括 EVT_CHAT_STATUS（mcp_tool_execution 阶段）、
 *         EVT_CHAT_NODE_COMPLETED（MCP_TOOL_EXECUTION 节点）、
 *         EVT_CHAT_CONDITION_EVALUATED（enter_mcp_tool / bypass_mcp_tool 路由）。
 * 为什么这样做：前端是后端的纯状态镜像，所有 MCP 状态更新都由后端推送驱动。
 * 输入输出：接收解析后的载荷，输出到 Zustand Store。
 * 边界条件：
 *   - 仅处理 message_id 匹配当前激活消息的事件。
 *   - 防乱序处理基于 sequence 字段。
 */
import { useMCPToolStore } from '../stores/mcpToolStore';
import type {
  ChatStatusPayload,
  ChatNodeStatusPayload,
  ChatConditionEvaluatedPayload,
} from '../../shared/types';

/**
 * 处理 EVT_CHAT_STATUS 事件中的 MCP 工具执行阶段。
 *
 * 做什么：当 stage 为 mcp_tool_execution 时，根据 state 值更新
 *         Store 中的 mcpToolStatus 状态。
 * 为什么这样做：前端是后端的纯状态镜像，所有状态更新都由后端推送驱动。
 * 输入输出：接收解析后的 ChatStatusPayload，输出到 Zustand Store。
 * 边界条件：
 *   - 仅处理 message_id 匹配当前激活消息的事件。
 *   - skipped 状态不会更新 enteredByCondition（保持之前的决策结果）。
 * 异常行为：payload 缺少关键字段时记录警告并跳过。
 */
export function handleMCPToolStatusEvent(payload: ChatStatusPayload): void {
  const store = useMCPToolStore.getState();

  // 防乱序：丢弃旧 sequence 的事件
  if (payload.sequence < store.lastMCPStatusSequence) {
    return;
  }
  store.setLastMCPStatusSequence(payload.sequence);

  switch (payload.state) {
    case 'running':
      store.setMCPToolStatus({
        enteredByCondition: true,
        conditionReason: payload.display_text || 'MCP 工具正在执行',
      });
      break;

    case 'completed':
      store.setToolCallCompleted(true);
      break;

    case 'skipped':
      // 跳过时不更新 enteredByCondition，保持上游决策结果
      break;

    case 'error':
      store.setMCPToolStatus({
        degraded: true,
        errorMessage: payload.error || 'MCP 工具执行遇到未知错误',
      });
      store.setToolCallCompleted(true);
      break;
  }
}

/**
 * 处理 EVT_CHAT_NODE_COMPLETED 事件中的 MCP 执行节点。
 *
 * 做什么：当 nodeType 为 mcp_tool_execution 时，从 payload 中提取
 *         执行耗时、降级状态等元数据并更新 Store。
 */
export function handleMCPNodeCompletedEvent(
  payload: ChatNodeStatusPayload,
): void {
  if (payload.nodeType !== 'mcp_tool_execution') {
    return;
  }

  const store = useMCPToolStore.getState();

  store.setMCPToolStatus({
    latencyMs: payload.latencyMs,
    degraded:
      payload.status === 'degraded' || payload.status === 'failed',
    degradedReason: payload.degradedReason || '',
    errorMessage: payload.errorCode
      ? `错误码: ${payload.errorCode}`
      : undefined,
  });
}

/**
 * 处理 EVT_CHAT_CONDITION_EVALUATED 事件中的 MCP 条件评估。
 *
 * 做什么：当 routeName 为 enter_mcp_tool 或 bypass_mcp_tool 时，
 *         记录条件评估结果。
 */
export function handleMCPConditionEvaluatedEvent(
  payload: ChatConditionEvaluatedPayload,
): void {
  if (
    payload.routeName !== 'enter_mcp_tool' &&
    payload.routeName !== 'bypass_mcp_tool'
  ) {
    return;
  }

  const store = useMCPToolStore.getState();

  store.setMCPToolStatus({
    enteredByCondition: payload.conditionEntered,
    conditionReason: payload.reason,
  });
}
