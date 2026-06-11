/**
 * MCP 节点详情面板（调试面板组件）。
 *
 * 做什么：在工作流调试面板中展示 MCP 工具执行节点的完整信息，包括：
 *         - 基础信息（节点类型、状态、耗时）
 *         - Agent 决策详情（推理过程、选择工具、参数）
 *         - 执行详情（输出、错误、重试）
 *         - 审计信息（风险等级、执行 ID）
 * 为什么这样做：为开发者提供完整的工具调用链路可观测性。
 * 边界条件：mcpToolStatus 为 null 时显示空数据提示。
 *           所有字段需做可选链和空值保护。
 */
import React from 'react';
import { useMCPToolStore } from '../../stores/mcpToolStore';

/**
 * MCP 节点详情组件。
 * 通过 Zustand Store 直接读取 MCP 工具执行状态，不需要额外的 props。
 * 可在调试面板的时间线视图中直接嵌入使用。
 */
export const MCPNodeDetail: React.FC = () => {
  const mcpStatus = useMCPToolStore((s) => s.mcpToolStatus);

  if (!mcpStatus) {
    return (
      <div className="mcp-node-detail">
        <div className="detail-card">
          <div className="card-body empty-text">
            暂无 MCP 工具执行数据
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mcp-node-detail">
      {/* Section 1: 基本信息 */}
      <div className="detail-card">
        <div className="card-title">基本信息</div>
        <div className="card-body">
          <div className="info-row">
            <span className="label">节点类型</span>
            <span className="value">MCP_TOOL_EXECUTION</span>
          </div>
          <div className="info-row">
            <span className="label">是否进入</span>
            <span className="value">
              {mcpStatus.enteredByCondition ? '是' : '否'}
            </span>
          </div>
          {mcpStatus.conditionReason && (
            <div className="info-row">
              <span className="label">进入原因</span>
              <span className="value">{mcpStatus.conditionReason}</span>
            </div>
          )}
          <div className="info-row">
            <span className="label">执行耗时</span>
            <span className="value">{mcpStatus.latencyMs ?? '-'}ms</span>
          </div>
          <div className="info-row">
            <span className="label">重试次数</span>
            <span className="value">{mcpStatus.retryCount ?? 0}</span>
          </div>
        </div>
      </div>

      {/* Section 2: Agent 决策详情 */}
      <div className="detail-card">
        <div className="card-title">Agent 决策详情</div>
        <div className="card-body">
          {mcpStatus.decision ? (
            <>
              <div className="info-row">
                <span className="label">需调用工具</span>
                <span className="value">
                  {mcpStatus.decision.shouldCallTool ? '是' : '否'}
                </span>
              </div>
              {mcpStatus.decision.toolName && (
                <div className="info-row">
                  <span className="label">选择工具</span>
                  <span className="value code">{mcpStatus.decision.toolName}</span>
                </div>
              )}
              {Object.keys(mcpStatus.decision.parameters || {}).length > 0 && (
                <div className="info-block">
                  <span className="label">调用参数</span>
                  <pre className="json-block">
                    {JSON.stringify(mcpStatus.decision.parameters, null, 2)}
                  </pre>
                </div>
              )}
              <div className="info-block">
                <span className="label">推理过程</span>
                <blockquote className="reasoning-text">
                  {mcpStatus.decision.reasoning || '无推理过程'}
                </blockquote>
              </div>
            </>
          ) : (
            <p className="empty-hint">无决策数据</p>
          )}
        </div>
      </div>

      {/* Section 3: 执行结果 */}
      <div className="detail-card">
        <div className="card-title">执行结果</div>
        <div className="card-body">
          {mcpStatus.executedToolName ? (
            <>
              <div className="info-row">
                <span className="label">执行工具</span>
                <span className="value code">{mcpStatus.executedToolName}</span>
              </div>
              <div className="info-row">
                <span className="label">执行 ID</span>
                <span className="value code">{mcpStatus.executionId || '-'}</span>
              </div>
              <div className="info-row">
                <span className="label">风险等级</span>
                <span className="value">{mcpStatus.riskLevel || '-'}</span>
              </div>
              <div className="info-block">
                <span className="label">输出文本</span>
                <pre className="output-block">
                  {mcpStatus.outputText || '无输出'}
                </pre>
              </div>
            </>
          ) : (
            <p className="empty-hint">未执行工具</p>
          )}

          {mcpStatus.errorMessage && (
            <div className="error-block">
              <span className="label error-label">错误信息</span>
              <p className="error-text">{mcpStatus.errorMessage}</p>
            </div>
          )}
        </div>
      </div>

      {/* Section 4: 降级详情 */}
      {mcpStatus.degraded && (
        <div className="detail-card degraded-card">
          <div className="card-title">降级详情</div>
          <div className="card-body">
            <p className="degraded-text">
              {mcpStatus.degradedReason || '未知降级原因'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};
