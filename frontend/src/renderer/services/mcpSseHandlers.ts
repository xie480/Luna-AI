/**
 * MCP SSE 事件处理器（含 Phase 13 Gating 权限治理）。
 *
 * 做什么：
 *   1. 处理 Phase 12 已有的 MCP 工具执行相关 SSE 事件（EVT_CHAT_STATUS、
 *      EVT_CHAT_NODE_COMPLETED、EVT_CHAT_CONDITION_EVALUATED）。
 *   2. 处理 Phase 13 新增的 Gating 鉴权事件（EVT_TOOL_AUTH_REQUIRED、
 *      EVT_PENDING_AUTHS_SYNC）。
 *   3. 提供 sendAuthResponse 函数，供 UI 层发送用户审批意图。
 *
 * 为什么这样做：遵循"瘦客户端"原则，前端仅作为后端的"状态投影"。
 * 所有鉴权数据的解析与验证都在此服务层完成，UI 组件只负责展示和触发。
 *
 * 输入输出：接收后端推送的 JSON 事件载荷，输出到 Zustand Store。
 * 边界条件：
 *   - Gating 事件来自 Python AI Service 的 SSE 推送，必须走 WS_MSG_TYPE 枚举。
 *   - 断线重连后，EVT_PENDING_AUTHS_SYNC 必须先调用 clearAll() 再入队。
 * 异常行为：非法的鉴权事件（缺少必填字段）会被记录错误日志并忽略。
 */
import { useAuthGatingStore } from '../stores/authGatingStore';
import { useAgentLoopStore } from '../stores/agentLoopStore';
import { useSystemStore } from '../stores/systemStore';
import { useMCPToolStore } from '../stores/mcpToolStore';
import type {
  ChatStatusPayload,
  ChatNodeStatusPayload,
  ChatConditionEvaluatedPayload,
  AuthRequiredPayload,
  PendingAuthsSyncPayload,
} from '../../shared/types';

// ============================================================
// Phase 12 已有：MCP 工具执行事件处理（sseManager 的分发目标）
// ============================================================

/**
 * 处理 EVT_CHAT_STATUS 事件中的 MCP 工具执行阶段。
 *
 * 做什么：当 stage 为 mcp_tool_execution 时，根据 state 值更新
 *        Store 中的 mcpToolStatus 状态。
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

// ============================================================
// Phase 13：Gating 鉴权事件处理
// ============================================================

/**
 * 最大的单次参数 JSON 字符串长度（字符数）。超过此长度时截断并在末尾追加截断标记。
 * 防止大模型"幻觉"输出极端大的参数对象导致前端渲染卡顿。
 */
const MAX_ARGUMENTS_JSON_LENGTH = 50000;

/**
 * 处理 EVT_TOOL_AUTH_REQUIRED 鉴权挂起事件。
 *
 * 做什么：将后端推送的高危工具鉴权请求解析并加入 Gating 挂起队列。
 * 为什么这样做：前端是后端的纯状态镜像，所有鉴权请求都由后端驱动。
 *             前端不做任何业务判断，仅做格式校验后入队展示。
 * 输入输出：接收后端推送的 AuthRequiredPayload，输出到 authGatingStore。
 * 边界条件：
 *   - 必须进行完整的格式校验，防止后端异常数据导致前端崩溃。
 *   - 入队时 authGatingStore 内部已经做了防重机制。
 *   - 过长的 arguments JSON 字符串会被截断以防止渲染卡顿。
 * 异常行为：
 *   - 缺少 audit_log_id、tool_id、tool_name、reason 中任一字段时，记录错误并返回。
 *   - 非法的 risk_level 值会被记录警告并降级为 'L2'。
 */
export function handleToolAuthRequired(message: {
  trace_id?: string;
  task_id?: string;
  timestamp?: number;
  payload: unknown;
}): void {
  const systemStore = useSystemStore.getState();
  const payload = message.payload as Record<string, unknown> | null;

  // ===== 格式硬防御：必须为合法对象 =====
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    console.error('[GatingHandler] 收到非法的鉴权挂起事件，payload 非对象:', message);
    systemStore.addSystemLog('收到非法的鉴权挂起事件：payload 格式错误');
    return;
  }

  // ===== 提取并校验必填字段 =====
  const audit_log_id = String(payload.audit_log_id ?? '');
  const tool_id = String(payload.tool_id ?? '');
  const tool_name = String(payload.tool_name ?? '');
  const reason = String(payload.reason ?? '');
  const rawRiskLevel = String(payload.risk_level ?? '');

  if (!audit_log_id || !tool_id || !tool_name || !reason) {
    console.error('[GatingHandler] 收到非法的鉴权挂起事件，缺少必填字段:', {
      audit_log_id,
      tool_id,
      tool_name,
      reason,
    });
    systemStore.addSystemLog('收到非法的鉴权挂起事件：缺少必填字段');
    return;
  }

  // ===== 校验 risk_level 枚举值 =====
  const validRiskLevels = ['L0', 'L1', 'L2', 'L3'] as const;
  type ValidRiskLevel = (typeof validRiskLevels)[number];
  const risk_level: ValidRiskLevel = validRiskLevels.includes(rawRiskLevel as ValidRiskLevel)
    ? (rawRiskLevel as ValidRiskLevel)
    : 'L2'; // 降级兜底：非法值默认为 L2

  if (rawRiskLevel !== risk_level) {
    console.warn(
      `[GatingHandler] 非法的 risk_level 值 "${rawRiskLevel}"，已降级为 L2`
    );
  }

  // ===== 参数载荷安全处理 =====
  const rawArguments = payload.arguments;
  // 检查 arguments 是否为合法 JSON 可序列化对象
  let safeArguments: unknown = rawArguments;
  if (rawArguments === null || rawArguments === undefined) {
    safeArguments = {};
  }
  // 验证 arguments 是否能被 JSON.stringify 正常处理（防止 BigInt/循环引用等）
  try {
    const jsonPreview = JSON.stringify(safeArguments);
    if (jsonPreview.length > MAX_ARGUMENTS_JSON_LENGTH) {
      console.warn(
        `[GatingHandler] arguments JSON 过长(${jsonPreview.length} 字符)，已截断`
      );
      safeArguments = {
        _truncated: true,
        _originalLength: jsonPreview.length,
        _preview: jsonPreview.substring(0, MAX_ARGUMENTS_JSON_LENGTH) + '...(已截断)',
      };
    }
  } catch {
    // arguments 可能包含不可序列化的数据结构，降级为字符串化
    console.warn('[GatingHandler] arguments 无法 JSON 序列化，降级为字符串');
    safeArguments = {
      _error: '无法序列化的参数数据结构',
      _rawType: typeof rawArguments,
    };
  }

  // ===== 入队 =====
  const authRequest = {
    audit_log_id,
    tool_id,
    tool_name,
    risk_level,
    reason,
    arguments: safeArguments,
    goal: String(payload.goal ?? ''),
    skill_info: payload.skill_info,
    agent_output: String(payload.agent_output ?? ''),
    trace_id: String(message.trace_id ?? ''),
    task_id: String(message.task_id ?? ''),
    timestamp: typeof message.timestamp === 'number' ? message.timestamp : Date.now(),
  };

  useAuthGatingStore.getState().enqueueRequest(authRequest);

  // ===== 同步更新 Agent Loop 面板中对应工具调用的审批状态为"等待审批" =====
  // 做什么：当 Agent Loop 模式下工具触发 Gating 时，在步骤卡片中将该工具调用标记为
  //         橙色"等待审批"状态，让用户在面板中也能直观看到哪些工具正在等待确认。
  // 为什么这样做：审批弹窗是全局阻断的，但 Agent Loop 面板中的工具调用列表也需要
  //               同步反映审批状态，避免"弹窗关闭后面板中看不到审批结果"的信息断层。
  useAgentLoopStore.getState().updateToolApprovalStatus(tool_name, 'awaiting_approval');

  systemStore.addSystemLog(
    `收到鉴权挂起事件: tool=${tool_name}, level=${risk_level}, audit_log_id=${audit_log_id}`
  );
}

/**
 * 处理 EVT_PENDING_AUTHS_SYNC 鉴权列表同步事件。
 *
 * 做什么：断线重连后，后端下发当前所有 PENDING_APPROVAL 状态的鉴权请求列表。
 *         前端必须先清空旧队列，再重新入队。
 * 为什么这样做：防止断线后后端的审批状态已变更，前端的陈旧卡片导致"状态撕裂"。
 *             一刀切的快照刷新是最可靠的恢复策略。
 * 输入输出：接收 PendingAuthsSyncPayload，输出到 authGatingStore。
 * 边界条件：requests 可能为空数组。
 * 异常行为：单个请求解析失败不影响其他请求的入队（容错处理）。
 */
export function handlePendingAuthsSync(payload: PendingAuthsSyncPayload): void {
  const systemStore = useSystemStore.getState();

  // 第一步：清空旧队列
  useAuthGatingStore.getState().clearAll();

  // 第二步：重新入队
  if (!payload.requests || !Array.isArray(payload.requests)) {
    systemStore.addSystemLog('收到鉴权列表同步事件，但 requests 非数组');
    return;
  }

  let validCount = 0;
  for (const req of payload.requests) {
    try {
      // 复用 handleToolAuthRequired 的处理逻辑，构造一个消息信封
      // 从 req 中提取 trace_id 和 task_id（后端 AuthRequestPayload 包含这些字段）
      handleToolAuthRequired({
        trace_id: req.trace_id || req.audit_log_id, // 优先使用后端下发的 trace_id
        task_id: req.task_id || '',
        timestamp: Date.now(),
        payload: req,
      });
      validCount++;
    } catch (err) {
      console.error('[GatingHandler] 同步鉴权列表时解析失败:', err, req);
    }
  }

  systemStore.addSystemLog(
    `收到鉴权列表同步事件: 共 ${payload.requests.length} 条，有效入队 ${validCount} 条`
  );
}

/**
 * 发送用户鉴权审批结果到后端。
 *
 * 做什么：将用户在 Gating 弹窗中的"同意/拒绝"意图包装为标准 WS 消息格式发送给后端。
 * 为什么这样做：前端只负责传递用户意图，不涉及任何业务逻辑判断和重试策略。
 *
 * 输入输出：
 *   输入：auditLogId、traceId、taskId、action、feedback。
 *   输出：通过 SSE（fetch POST）发送 CMD_TOOL_AUTH_RESPONSE 到后端。
 * 边界条件：
 *   - 连接断开时禁止发送，返回 false 并记录错误。
 *   - 发送成功后立即从队列中移除该请求，由 Zustand 状态的变更驱动 UI 重渲染。
 * 异常行为：
 *   - HTTP 请求失败时记录错误日志但不清除队列（交由重连后的同步机制处理）。
 *   - 请求超时（15秒）时自动放弃。
 *
 * @param backendUrl    后端 HTTP 基地址（如 http://127.0.0.1:8000）
 * @param auditLogId    鉴权日志 ID（雪花算法 string）
 * @param traceId       链路追踪 ID
 * @param taskId        关联任务 ID
 * @param action        用户审批动作：'APPROVE' | 'REJECT'
 * @param feedback      用户输入的反馈意见（可选）
 * @returns              发送成功返回 true，失败返回 false
 */
export async function sendAuthResponse(
  backendUrl: string,
  auditLogId: string,
  traceId: string,
  taskId: string,
  action: 'APPROVE' | 'REJECT',
  feedback: string = ''
): Promise<boolean> {
  const systemStore = useSystemStore.getState();

  // ===== 连接状态检查 =====
  if (systemStore.connectionStatus !== 'connected') {
    console.error(
      `[GatingHandler] 无法发送审批响应，连接状态为: ${systemStore.connectionStatus}`
    );
    systemStore.addSystemLog('无法发送审批响应：WebSocket/SSE 未连接');
    return false;
  }

  // ===== 参数合法性校验 =====
  // 注意：task_id 在后端 AuthResponseRequest 中为可选字段（默认空字符串），
  // 不强制要求非空，仅 auditLogId 和 traceId 为必填。
  if (!auditLogId || !traceId) {
    console.error('[GatingHandler] 发送审批响应失败：缺少必填参数', {
      auditLogId,
      traceId,
      taskId,
    });
    return false;
  }

  if (action !== 'APPROVE' && action !== 'REJECT') {
    console.error(`[GatingHandler] 非法的审批动作: ${action}`);
    return false;
  }

  // ===== 构造请求体（与后端 AuthResponseRequest 模型对齐） =====
  const requestBody = {
    audit_log_id: auditLogId,
    action,
    user_feedback: feedback || '',
    tool_id: '',
    task_id: taskId,
    session_id: '',
  };

  // ===== 通过 HTTP POST 发送到后端 =====
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000); // 15 秒超时

    const resp = await fetch(`${backendUrl}/api/gating/auth_response`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': traceId,
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!resp.ok) {
      const errorText = await resp.text().catch(() => '无响应体');
      console.error(
        `[GatingHandler] 发送审批响应失败: HTTP ${resp.status}, ${errorText}`
      );
      systemStore.addSystemLog(`发送审批响应失败: HTTP ${resp.status}`);
      // 注意：不清除队列，待重连同步机制处理
      return false;
    }

    // ===== 发送成功后移除队列中的请求 =====
    useAuthGatingStore.getState().removeRequest(auditLogId);

    const actionText = action === 'APPROVE' ? '已同意执行' : '已拒绝执行';
    systemStore.addSystemLog(
      `[TraceID:${traceId}] [TaskID:${taskId}] ${actionText} 工具鉴权请求: audit_log_id=${auditLogId}`
    );

    return true;
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);

    // 区分超时与其他异常
    if (err instanceof DOMException && err.name === 'AbortError') {
      console.error(`[GatingHandler] 发送审批响应超时 (15s): audit_log_id=${auditLogId}`);
      systemStore.addSystemLog(`发送审批响应超时: audit_log_id=${auditLogId}`);
    } else {
      console.error(`[GatingHandler] 发送审批响应异常: ${errMsg}`, { auditLogId, action });
      systemStore.addSystemLog(`发送审批响应异常: ${errMsg}`);
    }

    return false;
  }
}
