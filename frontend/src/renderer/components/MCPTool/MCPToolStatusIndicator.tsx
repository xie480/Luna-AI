/**
 * MCP 工具调用状态指示器。
 *
 * 做什么：在对话气泡区域顶部展示 MCP 工具执行的状态，包含以下阶段：
 *         - 未进入（无声，不展示）
 *         - 正在分析（展示"Luna 正在分析是否需要调用工具……"）
 *         - 正在调用（展示"Luna 正在调用 [工具名称]……"）
 *         - 调用完成（展示"Luna 已完成 [工具名称] 调用"）
 *         - 调用失败（展示"Luna 调用 [工具名称] 时遇到问题"）
 *         - 无需调用（无声，不展示）
 * 为什么这样做：让用户感知到系统正在主动执行工具操作，提升透明度和信任度。
 * 输入输出：从 Zustand Store 读取 mcpToolStatus。
 * 边界条件：mcpToolStatus 为 null 时不渲染任何内容。
 */
import React from 'react';
import { useMCPToolStore } from '../../stores/mcpToolStore';
import './MCPTool.css';

export const MCPToolStatusIndicator: React.FC = () => {
  const mcpToolStatus = useMCPToolStore((s) => s.mcpToolStatus);

  // 未进入 MCP 节点时，不显示任何内容
  if (!mcpToolStatus || !mcpToolStatus.enteredByCondition) {
    return null;
  }

  // 工具正在调用中（有 executedToolName 但没有 latencyMs 表示仍在执行）
  const isRunning =
    mcpToolStatus.executedToolName !== undefined && mcpToolStatus.latencyMs === undefined;
  // 工具已完成（latencyMs 存在且未降级）
  const isCompleted =
    mcpToolStatus.latencyMs !== undefined && mcpToolStatus.degraded !== true;
  // 工具已降级/失败
  const isDegraded = mcpToolStatus.degraded === true;
  // 工具决策完毕但不需调用
  const isNoToolNeeded = mcpToolStatus.decision?.shouldCallTool === false;

  if (isNoToolNeeded) {
    return null;
  }

  return (
    <div className="mcp-tool-status-indicator">
      <div className="mcp-tool-status-icon">
        {isRunning && <span className="spinner" />}
        {isCompleted && <span className="check-icon">✓</span>}
        {isDegraded && <span className="warning-icon">⚠</span>}
      </div>
      <div className="mcp-tool-status-text">
        {isRunning && (
          <span>Luna 正在调用 {mcpToolStatus.executedToolName}……</span>
        )}
        {isCompleted && (
          <span>Luna 已完成 {mcpToolStatus.executedToolName} 调用</span>
        )}
        {isDegraded && (
          <span>
            {mcpToolStatus.executedToolName
              ? `Luna 调用 ${mcpToolStatus.executedToolName} 时遇到问题`
              : 'Luna 工具调用遇到问题'}
          </span>
        )}
      </div>
      {mcpToolStatus.latencyMs !== undefined && (
        <div className="mcp-tool-status-meta">
          <span className="latency-badge">{mcpToolStatus.latencyMs}ms</span>
          {mcpToolStatus.retryCount !== undefined && mcpToolStatus.retryCount > 0 && (
            <span className="retry-badge">重试 {mcpToolStatus.retryCount} 次</span>
          )}
        </div>
      )}
    </div>
  );
};
