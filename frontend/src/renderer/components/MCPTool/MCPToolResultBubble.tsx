/**
 * MCP 工具调用结果气泡。
 *
 * 做什么：在对话流中展示工具调用的结果，以灰底气泡形式呈现。
 *         区别于用户消息和 AI 回复，工具结果气泡使用特殊样式。
 * 为什么这样做：让用户清晰区分"工具执行结果"和"AI 自然语言回复"。
 * 输入输出：从 Zustand Store 读取 mcpToolStatus。
 * 边界条件：仅当工具执行成功且有 outputText 时渲染。
 */
import React, { useMemo } from 'react';
import { useMCPToolStore } from '../../stores/mcpToolStore';
import './MCPTool.css';

export const MCPToolResultBubble: React.FC = () => {
  const mcpToolStatus = useMCPToolStore((s) => s.mcpToolStatus);

  const shouldRender = useMemo(() => {
    if (!mcpToolStatus) return false;
    // 仅当工具确实执行了且有输出时渲染
    return (
      mcpToolStatus.executedToolName !== undefined &&
      mcpToolStatus.outputText !== undefined &&
      mcpToolStatus.outputText.length > 0 &&
      mcpToolStatus.degraded !== true
    );
  }, [mcpToolStatus]);

  if (!shouldRender) {
    return null;
  }

  return (
    <div className="mcp-tool-result-bubble">
      <div className="mcp-tool-result-header">
        <span className="tool-icon">🔧</span>
        <span className="tool-name">{mcpToolStatus!.executedToolName}</span>
        <span className="tool-result-label">工具执行结果</span>
      </div>
      <div className="mcp-tool-result-body">
        <pre className="mcp-tool-output">{mcpToolStatus!.outputText}</pre>
      </div>
    </div>
  );
};
