/**
 * Phase 13：权限治理与前端 Gating 的 Zustand 全局状态 Store。
 *
 * 做什么：
 *   维护一个**强类型的挂起审批请求队列（Queue）**。当多 Agent 协作或主动感知后台任务
 *   引发并发权限请求时，所有请求排队等候用户处理。UI 每次仅展示队列最首部的一个请求。
 *
 * 为什么这样做：
 *   根据"投影视图"设计哲学，前端绝不能自己维护审批状态机。所有悬挂请求队列必须放置在
 *   全局 Zustand Store 中，并由后端 WebSocket 的主动下发或重连同步驱动更新。
 *
 * 边界条件：
 *   - 断线重连后，必须调用 clearAll() 清洗陈旧状态，再重新入队后端下发的有效请求。
 *   - enqueueRequest 具有防重机制：如果 audit_log_id 已存在，则丢弃重复消息。
 *   - removeRequest 仅在用户反馈已被 WS 发送成功后调用，确保"发送即生效"的语义。
 *
 * 异常行为：
 *   - 非法的 audit_log_id（空字符串、过长）会被记录错误日志并拒绝入队。
 *   - 队列最大长度限制为 50，超出时移除最旧的请求，防止内存泄漏。
 */
import { create } from 'zustand';

/**
 * Phase 13：鉴权请求事件载荷 —— 对应后端的 EVT_TOOL_AUTH_REQUIRED 事件。
 *
 * 做什么：定义后端推送至前端的挂起审批请求的完整数据结构。
 * 为什么这样做：确保前端渲染的每一字段都对应后端下发的可靠来源，禁止前端自造数据。
 * 输入输出：所有字段均由后端 JSON 序列化后推送。
 * 边界条件：
 *   - risk_level 必须是 'L0' | 'L1' | 'L2' | 'L3' 之一。
 *   - arguments 为任意 JSON 对象，前端必须使用 <pre> 按原始格式展示。
 *   - 可选字段（goal / skill_info / agent_output）可为 undefined。
 * 异常行为：audit_log_id 空值时拒绝入队。
 */
export interface AuthRequestPayload {
  /** 关联后端审计主键（雪花算法 ID 转换来的 string） */
  audit_log_id: string;
  /** 调用的工具标识（例如 mcp.local_fs.write_file） */
  tool_id: string;
  /** 友好显示的工具名称 */
  tool_name: string;
  /** 告警等级：L0 最低风险，L3 最高风险 */
  risk_level: 'L0' | 'L1' | 'L2' | 'L3';
  /** 后端策略引擎生成的阻拦原因解释 */
  reason: string;
  /** 参数载荷（例如 {"path":"...", "content":"..."}） */
  arguments: unknown;
  /** AI 当前执行的目标描述 */
  goal?: string;
  /** 相关的 SKILL 元信息 */
  skill_info?: unknown;
  /** SKILL 执行 Agent 的输出信息 */
  agent_output?: string;
  /** 链路追踪 ID */
  trace_id: string;
  /** 关联的计划任务 ID */
  task_id: string;
  /** 请求发生的时间戳（毫秒） */
  timestamp: number;
}

/**
 * 前端 Gating Store 的状态与 Action 接口。
 */
interface AuthGatingState {
  /** 当前挂起的审批请求队列，按入队时间正序排列。 */
  pendingRequests: AuthRequestPayload[];

  // ===== 供 Service 层调用的 Action（UI 层禁止直接调用 enqueueRequest） =====

  /**
   * 入队一条鉴权请求。
   * 做什么：将后端推送的 EVT_TOOL_AUTH_REQUIRED 解析结果添加到队列尾部。
   * 为什么这样做：防重机制避免网络抖动导致同一条消息被重复入队。
   * 输入输出：request 为后端推送的原始载荷。
   * 边界条件：
   *   - 如果 audit_log_id 已存在队列中，静默丢弃并记录警告。
   *   - 队列长度超过 MAX_QUEUE_SIZE（50）时，移除最旧的请求。
   * 异常行为：audit_log_id 为空字符串或 null 时拒绝入队。
   */
  enqueueRequest: (request: AuthRequestPayload) => void;

  /**
   * 从队列中移除一条鉴权请求。
   * 做什么：用户已审批（同意或拒绝）后，从 UI 队列中弹出该请求。
   * 为什么这样做：触发 React 重渲染，模态框自然关闭或显示下一条。
   * 输入输出：audit_log_id 标识要移除的请求。
   * 边界条件：如果 audit_log_id 不存在，静默忽略。
   */
  removeRequest: (audit_log_id: string) => void;

  /**
   * 清空整个审批队列。
   * 做什么：断线重连、会话切换或系统重置时，清除所有陈旧的挂起请求。
   * 为什么这样做：防止断连后后端的审批状态已变更，前端的陈旧卡片导致"状态撕裂"。
   * 边界条件：调用 clearAll 后，等待后端重新下发生效请求。
   */
  clearAll: () => void;
}

/** 队列最大长度，防止恶意浸灌导致内存泄漏。 */
const MAX_QUEUE_SIZE = 50;

/**
 * 创建 Gating Store 实例。
 * 严格遵循"投影视图"设计哲学：所有数据变更必须由后端驱动。
 */
export const useAuthGatingStore = create<AuthGatingState>((set) => ({
  pendingRequests: [],

  enqueueRequest: (request) =>
    set((state) => {
      // ===== 输入合法性校验 =====
      if (!request.audit_log_id || typeof request.audit_log_id !== 'string') {
        console.error('[authGatingStore] 拒绝入队：audit_log_id 无效', request);
        return state;
      }
      if (request.audit_log_id.length > 128) {
        console.error('[authGatingStore] 拒绝入队：audit_log_id 过长', request.audit_log_id.length);
        return state;
      }
      if (!request.tool_id || !request.tool_name || !request.reason) {
        console.error('[authGatingStore] 拒绝入队：缺少必填字段', {
          tool_id: request.tool_id,
          tool_name: request.tool_name,
          reason: request.reason,
        });
        return state;
      }

      // ===== 防重机制：避免因为网络抖动、重连导致收到同一条消息而在队列中疯狂叠加 =====
      if (state.pendingRequests.some((r) => r.audit_log_id === request.audit_log_id)) {
        console.warn(
          `[authGatingStore] 重复的鉴权请求已忽略: audit_log_id=${request.audit_log_id}, tool_name=${request.tool_name}`
        );
        return state;
      }

      // ===== 防溢出：超出最大长度时移除最旧的一条 =====
      const newQueue = [...state.pendingRequests, request];
      if (newQueue.length > MAX_QUEUE_SIZE) {
        const removed = newQueue.shift();
        console.warn(
          `[authGatingStore] 队列超出最大长度(${MAX_QUEUE_SIZE})，已移除最旧请求: audit_log_id=${removed?.audit_log_id}`
        );
      }

      return { pendingRequests: newQueue };
    }),

  removeRequest: (audit_log_id) =>
    set((state) => {
      if (!audit_log_id) return state;
      return {
        pendingRequests: state.pendingRequests.filter(
          (r) => r.audit_log_id !== audit_log_id
        ),
      };
    }),

  clearAll: () => {
    console.log('[authGatingStore] 已清空所有挂起的鉴权请求');
    return set({ pendingRequests: [] });
  },
}));
