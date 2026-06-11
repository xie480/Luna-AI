/**
 * MCP 工具调用失败/降级错误气泡。
 *
 * 做什么：当工具执行失败或降级时，展示错误信息和降级原因。
 * 为什么这样做：提供可视化的错误反馈，防止用户在无声情况下困惑。
 * 边界条件：仅当 degraded=true 且 errorMessage 非空时渲染。
 */
import React from 'react';
import { useMCPToolStore } from '../../stores/mcpToolStore';
import './MCPTool.css';

export const MCPToolErrorBubble: React.FC = () => {
  const mcpToolStatus = useMCPToolStore((s) => s.mcpToolStatus);

  if (!mcpToolStatus?.degraded || !mcpToolStatus.errorMessage) {
    return null;
  }

  return (
    <div className="mcp-tool-error-bubble">
      <div className="mcp-tool-error-header">
        <span className="error-icon">⚠️</span>
        <span className="error-text">工具调用异常</span>
      </div>
      <div className="mcp-tool-error-body">
        <p className="error-message">{mcpToolStatus.errorMessage}</p>
        {mcpToolStatus.executedToolName && (
          <p className="error-tool-name">
            涉及工具: {mcpToolStatus.executedToolName}
          </p>
        )}
      </div>
    </div>
  );
};
