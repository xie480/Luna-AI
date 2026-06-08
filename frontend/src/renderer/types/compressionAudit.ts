import {
  COMPRESSION_AUDIT_SCHEMA_VERSION,
  COMPRESSION_EVENT_SCHEMA_VERSION,
  COMPRESSION_REPLAY_SCHEMA_VERSION,
  COMPRESSION_SCOPE,
  COMPRESSION_STAGE,
  COMPRESSION_STATUS,
  COMPRESSION_TRIGGER_REASON,
} from '../../shared/enum';

/**
 * 压缩阶段类型。
 *
 * 做什么：约束前端所有压缩阶段字段只能使用后端稳定枚举值。
 * 为什么这样做：避免列表、详情、筛选和复制摘要中散落魔法字符串。
 * 输入输出：无运行时输入，作为 TypeScript 联合类型提供静态约束。
 * 边界条件：新增阶段时必须先扩展共享枚举，再同步此类型。
 * 异常行为：无。
 */
export type CompressionStage = typeof COMPRESSION_STAGE[keyof typeof COMPRESSION_STAGE];

/**
 * 压缩作用域类型。
 *
 * 做什么：约束压缩记录中 scope 字段的允许值。
 * 为什么这样做：后端存在 session_history、memory_slot 等多类作用域，前端必须统一消费。
 * 输入输出：无运行时输入，作为静态类型导出。
 * 边界条件：允许覆盖当前后端已返回的全部作用域枚举。
 * 异常行为：无。
 */
export type CompressionScope = typeof COMPRESSION_SCOPE[keyof typeof COMPRESSION_SCOPE];

/**
 * 压缩基础状态类型。
 *
 * 做什么：表示后端稳定返回的压缩执行状态。
 * 为什么这样做：与“显示态”区分，避免把前端派生标签误当成后端真实状态。
 * 输入输出：无。
 * 边界条件：仅包含后端当前真实落盘的 SUCCESS / FAILED / SKIPPED。
 * 异常行为：无。
 */
export type CompressionAuditStatus = typeof COMPRESSION_STATUS[keyof typeof COMPRESSION_STATUS];

/**
 * 压缩列表/详情展示状态。
 *
 * 做什么：在基础状态之上补充“已降级”和“强制截断”两类前端可视化标签。
 * 为什么这样做：验收要求必须显式区分普通成功、降级成功与强制截断场景。
 * 输入输出：无。
 * 边界条件：该类型仅用于展示，不回写后端。
 * 异常行为：无。
 */
export type CompressionAuditDisplayStatus =
  | CompressionAuditStatus
  | 'DEGRADED'
  | 'HARD_TRUNCATED';

/**
 * 压缩触发原因类型。
 *
 * 做什么：约束 trigger_reason 字段与后端枚举保持一致。
 * 为什么这样做：筛选器、详情卡片和复制摘要都依赖稳定原因值。
 * 输入输出：无。
 * 边界条件：未知值会在服务层归一化为 final_prompt_token_over_limit。
 * 异常行为：无。
 */
export type CompressionTriggerReason = typeof COMPRESSION_TRIGGER_REASON[keyof typeof COMPRESSION_TRIGGER_REASON];

/**
 * 压缩动作阶段时间线事件。
 *
 * 做什么：表达单个阶段在回放详情中的最小可观测单元。
 * 为什么这样做：列表只负责定位，详情必须能深入查看阶段指标、模型信息和脱敏预览。
 * 输入输出：由服务层结构化生成，供详情抽屉直接消费。
 * 边界条件：模型字段允许为空，表示该阶段没有触发模型压缩。
 * 异常行为：无。
 */
export interface CompressionReplayEvent {
  schema_version: string;
  replay_snapshot_id: string;
  stage: CompressionStage;
  scope: CompressionScope;
  trigger_reason: CompressionTriggerReason;
  source_keys: string[];
  raw_tokens: number;
  after_trim_tokens: number;
  after_summary_tokens: number;
  final_tokens: number;
  stage_compression_ratio: number;
  total_compression_ratio: number;
  model_provider: string;
  model_base_url: string;
  model_id: string;
  trace_id: string;
  session_id: string;
  message_id: string;
  preview_before: string;
  preview_after: string;
  is_success: boolean;
  failure_reason: string;
  timestamp_ms: number;
  timestamp_iso: string;
  display_status: CompressionAuditDisplayStatus;
}

/**
 * 压缩审计列表项。
 *
 * 做什么：表达压缩审计表格的一行数据。
 * 为什么这样做：列表层关注快速定位问题，需要比详情更轻量、更稳定的字段集合。
 * 输入输出：由服务层归一化生成，供列表、分页、筛选和回放入口消费。
 * 边界条件：message_id 允许为空，表示链路是会话级或记忆级压缩。
 * 异常行为：无。
 */
export interface CompressionAuditListItem {
  schema_version: string;
  id: string;
  trace_id: string;
  session_id: string;
  message_id: string;
  replay_snapshot_id: string;
  stage: CompressionStage;
  scope: CompressionScope;
  trigger_reason: CompressionTriggerReason;
  raw_tokens: number;
  final_tokens: number;
  total_compression_ratio: number;
  status: CompressionAuditStatus;
  display_status: CompressionAuditDisplayStatus;
  final_strategy: string;
  failure_reason: string;
  timestamp: string;
  timestamp_ms: number;
}

/**
 * 压缩回放总览摘要。
 *
 * 做什么：表达单条 Trace 的压缩总览信息。
 * 为什么这样做：详情抽屉顶部需要稳定摘要，而不是在组件中动态扫描事件数组。
 * 输入输出：由服务层生成，供总览卡片与复制摘要共用。
 * 边界条件：started_at 允许为空字符串，表示没有可用的事件时间。
 * 异常行为：无。
 */
export interface CompressionReplaySummary {
  schema_version: string;
  raw_tokens: number;
  final_tokens: number;
  total_compression_ratio: number;
  final_strategy: string;
  is_success: boolean;
  failure_reason: string;
  started_at: string;
  display_status: CompressionAuditDisplayStatus;
}

/**
 * 压缩 Span 数据。
 *
 * 做什么：承载与压缩阶段关联的链路耗时信息。
 * 为什么这样做：回放详情需要保留到 TraceViewer 的联动上下文。
 * 输入输出：由后端 replay 接口或服务层兼容逻辑生成。
 * 边界条件：attributes 允许为空对象。
 * 异常行为：无。
 */
export interface CompressionReplaySpan {
  span_id: string;
  name: string;
  service: string;
  duration_ms: number;
  status: string;
  start_time: string | null;
  end_time: string | null;
  attributes: Record<string, unknown>;
}

/**
 * 压缩回放详情。
 *
 * 做什么：表达单次 Trace 的可回放压缩链路完整结构。
 * 为什么这样做：诊断抽屉必须同时展示总览、时间线、阶段详情和联动数据。
 * 输入输出：由服务层统一归一化，组件层不再直接解析原始 JSON。
 * 边界条件：events 可为空，表示当前链路没有可展示的压缩快照。
 * 异常行为：无。
 */
export interface CompressionReplayDetail {
  schema_version: string;
  trace_id: string;
  session_id: string;
  message_id: string;
  summary: CompressionReplaySummary;
  events: CompressionReplayEvent[];
  spans: CompressionReplaySpan[];
}

/**
 * 压缩审计筛选条件。
 *
 * 做什么：统一定义列表页支持的筛选字段。
 * 为什么这样做：Store、服务层与组件表单必须共享同一套查询契约。
 * 输入输出：由 UI 表单写入，再交给服务层执行本地兼容过滤。
 * 边界条件：所有字段都允许为空，代表不启用该筛选条件。
 * 异常行为：无。
 */
export interface CompressionAuditFilters {
  start_time?: string;
  end_time?: string;
  stage?: CompressionStage;
  scope?: CompressionScope;
  status?: CompressionAuditDisplayStatus;
  trigger_reason?: CompressionTriggerReason;
  trace_id?: string;
  session_id?: string;
}

/**
 * 压缩审计列表查询参数。
 *
 * 做什么：约束分页和筛选参数的传递结构。
 * 为什么这样做：避免服务层直接接收零散参数，降低组件与接口耦合度。
 * 输入输出：输入分页参数与筛选条件，输出给服务层请求函数。
 * 边界条件：page 从 1 开始；pageSize 必须为正整数。
 * 异常行为：无。
 */
export interface FetchCompressionAuditsParams {
  page: number;
  pageSize: number;
  filters: CompressionAuditFilters;
}

/**
 * 压缩审计列表响应。
 *
 * 做什么：表达前端已归一化的分页结果。
 * 为什么这样做：列表组件只关注 items/total，不依赖后端具体包装格式。
 * 输入输出：服务层返回给列表组件。
 * 边界条件：items 允许为空数组。
 * 异常行为：无。
 */
export interface CompressionAuditListResponse {
  items: CompressionAuditListItem[];
  total: number;
}

/** 压缩审计协议版本。 */
export const FRONTEND_COMPRESSION_AUDIT_SCHEMA_VERSION = COMPRESSION_AUDIT_SCHEMA_VERSION;

/** 压缩事件协议版本。 */
export const FRONTEND_COMPRESSION_EVENT_SCHEMA_VERSION = COMPRESSION_EVENT_SCHEMA_VERSION;

/** 压缩回放协议版本。 */
export const FRONTEND_COMPRESSION_REPLAY_SCHEMA_VERSION = COMPRESSION_REPLAY_SCHEMA_VERSION;
