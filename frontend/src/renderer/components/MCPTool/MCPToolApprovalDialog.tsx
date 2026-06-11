/**
 * MCP 工具调用审批对话框（Phase 13 预留骨架）。
 *
 * 做什么：当后端推送的工具决策 requiresUserApproval=true 时，
 *         弹出此对话框让用户确认是否允许执行高危工具。
 * 为什么这样做：L2 级及以上风险工具必须经过用户确认才能执行。
 * 边界条件：当前 Phase 12 所有工具均为 L0 级，requiresUserApproval 始终为 false。
 *           此组件在 Phase 13 中激活。
 */
import React from 'react';
import { useMCPToolStore } from '../../stores/mcpToolStore';

/**
 * 待审批的工具调用信息。
 */
interface PendingApproval {
  executionId: string;
  toolName: string;
  parameters: Record<string, unknown>;
  reasoning: string;
}

export const MCPToolApprovalDialog: React.FC = () => {
  const mcpToolStatus = useMCPToolStore((s) => s.mcpToolStatus);

  // Phase 12: requiresUserApproval 始终为 false，不弹窗
  const pendingApproval: PendingApproval | null =
    mcpToolStatus?.decision?.requiresUserApproval &&
    mcpToolStatus.decision.shouldCallTool
      ? {
          executionId: mcpToolStatus.executionId || '',
          toolName: mcpToolStatus.decision.toolName,
          parameters: mcpToolStatus.decision.parameters,
          reasoning: mcpToolStatus.decision.reasoning,
        }
      : null;

  if (!pendingApproval) {
    return null;
  }

  return (
    <div className="mcp-approval-dialog-overlay">
      <div className="mcp-approval-dialog">
        <div className="approval-header">
          <h3>🔐 工具调用确认</h3>
          <p>Luna 请求执行以下操作，请确认是否允许：</p>
        </div>

        <div className="approval-body">
          <div className="approval-info">
            <span className="info-label">工具名称</span>
            <span className="info-value">{pendingApproval.toolName}</span>
          </div>
          <div className="approval-info">
            <span className="info-label">执行 ID</span>
            <span className="info-value">{pendingApproval.executionId}</span>
          </div>
          {Object.keys(pendingApproval.parameters).length > 0 && (
            <div className="approval-params">
              <span className="info-label">参数</span>
              <pre>{JSON.stringify(pendingApproval.parameters, null, 2)}</pre>
            </div>
          )}
          <div className="approval-reasoning">
            <span className="info-label">推理过程</span>
            <blockquote>{pendingApproval.reasoning}</blockquote>
          </div>
        </div>

        <div className="approval-footer">
          <button className="btn-approval-deny">拒绝</button>
          <button className="btn-approval-allow">允许</button>
        </div>
      </div>
    </div>
  );
};
