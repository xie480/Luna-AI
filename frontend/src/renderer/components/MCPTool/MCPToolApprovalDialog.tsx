/**
 * Phase 13：权限治理与前端 Gating 的全局阻断审批弹窗组件。
 *
 * 做什么：
 *   当 Python 后端推送到高危工具（L2/L3 级）鉴权挂起事件（EVT_TOOL_AUTH_REQUIRED）时，
 *   此组件会渲染一个全屏蒙层（Z-Index 高于一切 UI），强制阻断用户与底层界面的交互，
 *   并展示高危操作的详细参数，等待用户做出"放行"或"拒绝"的审批决策。
 *
 * 为什么这样做：
 *   遵循"瘦客户端"设计原则，前端是后端的纯状态投影。所有鉴权数据由 authGatingStore
 *   维护，UI 只负责展示和触发用户交互。本组件不缓存任何审批状态。
 *
 * 安全设计：
 *   1. 防误触：批准按钮需要点击两次确认（第一次激活确认态，3 秒内再点生效）。
 *   2. 连接感知：断线状态下按钮禁用并显示提示，防止发送脏数据。
 *   3. 队列管理：当多个请求挂起时，每次只展示队首一个，右上角显示排队数量。
 *   4. 键盘劫持：阻止 Esc 键和右键菜单关闭弹窗。
 *   5. 参数透明：arguments 必须以格式化 JSON 原始展示，不可隐藏任何参数。
 *
 * 边界条件：
 *   - 队列为空时返回 null，不渲染任何内容。
 *   - 断线重连后，后端推送 EVT_PENDING_AUTHS_SYNC 时会清洗旧队列。
 *   - 弹窗内部使用 ErrorBoundary 防止单一渲染错误导致整体白屏。
 * 异常行为：
 *   - 参数 JSON 显示异常被 ErrorBoundary 捕获，不影响其他组件。
 *   - HTTP 请求超时时返回发送失败提示，不清除队列。
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useAuthGatingStore } from '../../stores/authGatingStore';
import { useSystemStore } from '../../stores/systemStore';
import { sendAuthResponse } from '../../services/mcpSseHandlers';
import { AI_SERVICE_BASE_URL } from '../../appConfig';
import ErrorBoundary from '../ErrorBoundary/ErrorBoundary';
import './MCPTool.css';

/**
 * Phase 13：风险等级对应的中文标签。
 * 做什么：在 UI 上展示用户可理解的风险等级描述。
 */
const RISK_LEVEL_LABEL: Record<string, string> = {
  L0: '无风险',
  L1: '低风险',
  L2: '中高风险',
  L3: '致命风险',
};

/**
 * Phase 13：风险等级对应的 CSS 类名后缀。
 * 做什么：用于切换不同风险等级下的徽章样式。
 */
const RISK_LEVEL_CLASS: Record<string, string> = {
  L0: 'level-l0',
  L1: 'level-l1',
  L2: 'level-l2',
  L3: 'level-l3',
};

/**
 * MCPToolApprovalOverlay：全局 Gating 审批弹窗组件。
 *
 * 做什么：全屏蒙层阻断用户操作，展示单个鉴权请求详情并等待审批。
 * 为什么这样做：L2 级及以上风险工具必须经过用户当面确认才能执行。
 * 输入输出：读取 authGatingStore.pendingRequests 队列，调用 sendAuthResponse 发送结果。
 * 边界条件：
 *   - 订阅 systemStore.connectionStatus，断线时按钮禁用。
 *   - 防误触机制：批准按钮需 2 次点击，3 秒内确认。
 * 异常行为：内层渲染错误由 ErrorBoundary 捕获，显示降级 UI。
 */
const MCPToolApprovalOverlayInner: React.FC = () => {
  // ===== 订阅全局状态 =====
  const pendingRequests = useAuthGatingStore((state) => state.pendingRequests);
  const connectionStatus = useSystemStore((state) => state.connectionStatus);
  const addSystemLog = useSystemStore((state) => state.addSystemLog);

  // ===== 组件本地状态 =====
  /** 防误触：批准按钮的二次确认状态 */
  const [isConfirming, setIsConfirming] = useState(false);
  /** 正在发送请求的标志，防止重复提交 */
  const [isSending, setIsSending] = useState(false);
  /** 用户输入的反馈意见 */
  const [feedback, setFeedback] = useState('');
  /** 发送失败的错误信息（用于 UI 提示） */
  const [sendError, setSendError] = useState<string | null>(null);

  /** 二次确认的计时器引用，用于组件卸载时清除 */
  const confirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** 后端 HTTP 基地址 */
  const backendUrl = AI_SERVICE_BASE_URL;

  // ===== 清理二次确认状态 =====
  const resetConfirmState = useCallback(() => {
    setIsConfirming(false);
    if (confirmTimerRef.current) {
      clearTimeout(confirmTimerRef.current);
      confirmTimerRef.current = null;
    }
  }, []);

  // 组件卸载时清除定时器
  useEffect(() => {
    return () => {
      if (confirmTimerRef.current) {
        clearTimeout(confirmTimerRef.current);
      }
    };
  }, []);

  // 当队列变化时，重置二次确认状态（切换到下一个请求时自动重置）
  useEffect(() => {
    resetConfirmState();
    setSendError(null);
    setFeedback('');
  }, [pendingRequests.length, resetConfirmState]);

  // ===== 总是展示队列头部的第一条数据（Hooks 之后才能读取） =====
  const currentReq = pendingRequests[0];
  const queueLength = pendingRequests.length;
  const isDisconnected = connectionStatus !== 'connected';

  /**
   * 处理用户的审批动作（同意或拒绝）。
   *
   * 做什么：将用户意图包装为 AuthResponsePayload 发送到后端。
   * 为什么这样做：前端只传递意图，不参与业务判断。
   * 输入输出：调用 sendAuthResponse 发送 HTTP 请求。
   * 边界条件：
   *   - 断线时禁止发送。
   *   - 发送中禁止重复点击。
   *   - 发送失败时不清除队列，等待重连同步。
   * 异常行为：HTTP 请求超时或网络异常时设置 sendError 提示。
   */
  const handleAction = useCallback(
    async (action: 'APPROVE' | 'REJECT') => {
      // 防止重复提交
      if (isSending) return;
      // 断线保护
      if (isDisconnected) {
        addSystemLog('无法发送审批响应：SSE 未连接');
        return;
      }

      setIsSending(true);
      setSendError(null);

      try {
        const success = await sendAuthResponse(
          backendUrl,
          currentReq?.audit_log_id ?? '',
          currentReq?.trace_id ?? '',
          currentReq?.task_id ?? '',
          action,
          feedback,
        );

        if (!success) {
          setSendError('发送审批结果失败，请等待网络恢复后重试');
          // 注意：不清除队列，等待重连同步机制处理
        }
        // 发送成功时，sendAuthResponse 内部已调用 removeRequest
        // 队列更新后，组件会自然切换到下一条或关闭
      } catch (err) {
        const errMsg = err instanceof Error ? err.message : String(err);
        setSendError(`发送异常: ${errMsg}`);
        addSystemLog(`发送审批响应异常: ${errMsg}`);
      } finally {
        setIsSending(false);
        resetConfirmState();
      }
    },
    [isSending, isDisconnected, currentReq, feedback, backendUrl, addSystemLog, resetConfirmState],
  );

  /**
   * 处理批准按钮的点击。
   * 防误触逻辑：第一次点击进入确认态，3 秒内再点击才真正的 APPROVE。
   */
  const handleApproveClick = useCallback(() => {
    if (isConfirming) {
      // 第二次点击：执行真正的 APPROVE
      handleAction('APPROVE');
    } else {
      // 第一次点击：进入确认态
      setIsConfirming(true);
      confirmTimerRef.current = setTimeout(() => {
        setIsConfirming(false);
      }, 3000);
    }
  }, [isConfirming, handleAction]);

  /**
   * 处理拒绝按钮的点击。
   * 拒绝是一键操作，无需二次确认。
   */
  const handleRejectClick = useCallback(() => {
    handleAction('REJECT');
  }, [handleAction]);

  // ============================================================
  // 阻止键盘事件：防止 Esc 键或回车键误操作
  // ============================================================
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape' || e.key === 'Esc') {
      e.preventDefault();
      e.stopPropagation();
    }
  }, []);

  // ============================================================
  // 阻止右键菜单
  // ============================================================
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  // ===== 队列为空的兜底（必须在所有 Hooks 调用之后，否则违反 Rules of Hooks） =====
  if (pendingRequests.length === 0) {
    return null;
  }

  /**
   * 安全渲染 arguments 参数载荷。
   * 做什么：将后端推送的 arguments 以格式化 JSON 展示。
   * 为什么这样做：根据设计规范，参数载荷必须一字不差地向用户展示。
   * 边界条件：arguments 可能包含各种数据类型，统一 JSON 序列化处理。
   */
  const renderArguments = (args: unknown): string => {
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      // 极端情况：如果 JSON.stringify 失败（如循环引用），降级展示
      return String(args);
    }
  };

  return (
    <div
      className="gating-overlay"
      onKeyDown={handleKeyDown}
      onContextMenu={handleContextMenu}
      tabIndex={-1}
    >
      <div className="gating-modal gating-modal-cyberpunk">
        {/* ===== 多队列提示 ===== */}
        {queueLength > 1 && (
          <div className="gating-queue-notice">
            ⏳ 还有 {queueLength - 1} 个后台操作正在排队等待审批...
          </div>
        )}

        {/* ===== 头部警告区域 ===== */}
        <div className="gating-header">
          <span className="gating-warning-icon" aria-hidden="true">
            ⚠️
          </span>
          <h2 className="gating-title">Luna 想要执行以下高风险操作</h2>
        </div>

        {/* ===== 主体信息区域 ===== */}
        <div className="gating-body">
          {/* 当前目标 */}
          <div className="gating-info-row">
            <span className="gating-label">当前目标 (Goal)：</span>
            <span className="gating-value">
              {currentReq.goal || '未提供目标描述'}
            </span>
          </div>

          {/* AI 思考/输出 */}
          {currentReq.agent_output && (
            <div className="gating-info-row">
              <span className="gating-label">AI 推理过程：</span>
              <span className="gating-value gating-agent-output">
                {currentReq.agent_output}
              </span>
            </div>
          )}

          {/* 所属 SKILL */}
          {currentReq.skill_info && typeof currentReq.skill_info === 'object' && (
            <div className="gating-info-row">
              <span className="gating-label">所属 SKILL：</span>
              <span className="gating-value">
                {(currentReq.skill_info as Record<string, unknown>).name
                  ? String((currentReq.skill_info as Record<string, unknown>).name)
                  : '未知 SKILL'}
              </span>
            </div>
          )}

          {/* 工具名称 */}
          <div className="gating-info-row">
            <span className="gating-label">将调用组件：</span>
            <span className="gating-value gating-tool-name">
              {currentReq.tool_name}
              <span className="gating-tool-id">（{currentReq.tool_id}）</span>
            </span>
          </div>

          {/* 风险等级徽章 */}
          <div className="gating-info-row">
            <span className="gating-label">警戒等级：</span>
            <span
              className={`gating-risk-badge ${RISK_LEVEL_CLASS[currentReq.risk_level] || 'level-l2'}`}
            >
              {currentReq.risk_level} - {RISK_LEVEL_LABEL[currentReq.risk_level] || '未知风险'}
            </span>
          </div>

          {/* 拦截原因 */}
          <div className="gating-info-row">
            <span className="gating-label">安全拦截原因：</span>
            <span className="gating-value gating-reason">{currentReq.reason}</span>
          </div>

          {/* 参数载荷 —— 必须以格式化 JSON 原始展示 */}
          <div className="gating-param-section">
            <span className="gating-label">将要注入执行的原始参数载荷：</span>
            <pre className="gating-json-block">
              {renderArguments(currentReq.arguments)}
            </pre>
          </div>

          {/* 反馈输入框 */}
          <div className="gating-feedback-section">
            <label className="gating-label" htmlFor="gating-feedback-input">
              💬 提供修正意见或拒绝原因给 AI（可选）：
            </label>
            <textarea
              id="gating-feedback-input"
              className="gating-cyber-input"
              rows={3}
              placeholder="例如：请不要格式化整个目录，只读取该目录下的 txt 文件即可。"
              value={feedback}
              onChange={(e) => {
                // 限制反馈文本最大长度为 2000 字符
                if (e.target.value.length <= 2000) {
                  setFeedback(e.target.value);
                }
              }}
              disabled={isSending}
            />
            <span className="gating-feedback-counter">
              {feedback.length} / 2000
            </span>
          </div>

          {/* 发送错误提示 */}
          {sendError && (
            <div className="gating-error-message">
              ❌ {sendError}
            </div>
          )}

          {/* 断线提示 */}
          {isDisconnected && (
            <div className="gating-disconnected-notice">
              ⚠️ 连接已断开，请等待重新连接后再进行审批操作
            </div>
          )}
        </div>

        {/* ===== 底部操作按钮 ===== */}
        <div className="gating-actions">
          {/* 拒绝按钮：一键拒绝，无需二次确认 */}
          <button
            className="gating-btn gating-btn-danger"
            onClick={handleRejectClick}
            disabled={isSending || isDisconnected}
            aria-label="拒绝此操作"
          >
            ❌ 严词拒绝并阻断
          </button>

          {/* 批准按钮：防误触二次确认机制 */}
          <button
            className={`gating-btn gating-btn-warning ${isConfirming ? 'gating-btn-confirming' : ''}`}
            onClick={handleApproveClick}
            disabled={isSending || isDisconnected}
            aria-label={isConfirming ? '再次点击以确认执行' : '风险自担，我要放行'}
          >
            {isSending
              ? '⏳ 发送中...'
              : isConfirming
                ? '✅ 再次点击确认执行'
                : '⚠️ 风险自担，我要放行'}
          </button>
        </div>
      </div>
    </div>
  );
};

/**
 * 导出带 ErrorBoundary 的 Gating 弹窗组件。
 *
 * 做什么：在 MCPToolApprovalOverlayInner 外层包裹 ErrorBoundary，
 *         防止内部渲染崩溃导致整个应用白屏。
 * 为什么这样做：设计规范要求 Gating 弹窗必须带有崩溃恢复能力。
 * 边界条件：ErrorBoundary 捕获异常后展示降级 UI，底部提供"重试"按钮。
 */
const MCPToolApprovalOverlay: React.FC = () => {
  return (
    <ErrorBoundary
      source="mcp_gating_overlay"
      fallback={
        <div
          className="gating-overlay"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#e74c3c',
            fontSize: 16,
          }}
        >
          <div
            className="gating-modal gating-modal-cyberpunk"
            style={{ textAlign: 'center', padding: 40 }}
          >
            <p>⚠️ 安全审批面板发生异常，请尝试刷新或联系技术支持。</p>
            <button
              className="gating-btn gating-btn-danger"
              onClick={() => {
                window.location.reload();
              }}
            >
              🔄 刷新应用
            </button>
          </div>
        </div>
      }
    >
      <MCPToolApprovalOverlayInner />
    </ErrorBoundary>
  );
};

export default MCPToolApprovalOverlay;
export { MCPToolApprovalOverlay };
