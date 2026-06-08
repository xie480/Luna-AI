import { AI_SERVICE_BASE_URL } from '../appConfig';
import {
  COMPRESSION_AUDIT_ACTION_TYPE,
  COMPRESSION_AUDIT_SCHEMA_VERSION,
  COMPRESSION_REPLAY_SCHEMA_VERSION,
  COMPRESSION_SCOPE,
  COMPRESSION_STAGE,
  COMPRESSION_STATUS,
  COMPRESSION_TRIGGER_REASON,
} from '../../shared/enum';
import type {
  CompressionAuditDisplayStatus,
  CompressionAuditFilters,
  CompressionAuditListItem,
  CompressionAuditListResponse,
  CompressionAuditStatus,
  CompressionReplayDetail,
  CompressionReplayEvent,
  CompressionReplaySpan,
  CompressionScope,
  CompressionStage,
  CompressionTriggerReason,
  FetchCompressionAuditsParams,
} from '../types/compressionAudit';

/** 压缩审计 API 基础 URL。 */
const TELEMETRY_BASE = `${AI_SERVICE_BASE_URL}/api/v1/telemetry`;

/** 压缩审计 HTTP 请求超时时间。 */
const COMPRESSION_AUDIT_REQUEST_TIMEOUT_MS = 8000;

/** 专用接口不可用时，从通用审计日志兜底拉取的最大记录数。 */
const FALLBACK_AUDIT_LOG_LIMIT = 500;

/** 需要前端本地二次过滤的字段集合。 */
const CLIENT_FILTER_KEYS: Array<keyof CompressionAuditFilters> = [
  'start_time',
  'end_time',
  'stage',
  'scope',
  'trigger_reason',
  'session_id',
];

/** 后端统一响应结构的最小前端读模型。 */
interface ApiEnvelope {
  code?: number;
  msg?: string;
  data?: unknown;
  total?: number;
}

/** 通用审计日志兼容结构。 */
interface RawAuditLogEnvelope {
  id?: unknown;
  trace_id?: unknown;
  action_type?: unknown;
  status?: unknown;
  details?: unknown;
  error_msg?: unknown;
  timestamp?: unknown;
}

/**
 * 判断值是否是可索引对象。
 *
 * 做什么：为服务层解析未知 JSON 提供统一类型保护。
 * 为什么这样做：后端在专用接口和通用审计兜底接口中的包装层不同，不能假设输入一定合法。
 * 输入输出：输入 unknown，输出是否为 Record<string, unknown>。
 * 边界条件：数组与 null 均返回 false。
 * 异常行为：本函数不抛异常。
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * 将未知值安全转为字符串。
 *
 * 做什么：统一处理 ID、原因、模型信息等字符串字段。
 * 为什么这样做：审计 details 可能来自 JSON 字符串或旧结构，字段缺失时必须有空态兜底。
 * 输入输出：输入 unknown 与默认值，输出字符串。
 * 边界条件：null/undefined 返回默认值。
 * 异常行为：本函数不抛异常。
 */
function toStringValue(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback;
  return String(value);
}

/**
 * 将未知值安全转为数字。
 *
 * 做什么：统一处理 Token 与压缩率字段。
 * 为什么这样做：接口契约要求 number，但兼容兜底解析时仍需防止字符串或非法值导致 UI 崩溃。
 * 输入输出：输入 unknown 与默认值，输出有限数字。
 * 边界条件：NaN 和 Infinity 均返回默认值。
 * 异常行为：本函数不抛异常。
 */
function toNumberValue(value: unknown, fallback = 0): number {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

/**
 * 将未知值安全转为布尔值。
 *
 * 做什么：统一处理 is_success 字段。
 * 为什么这样做：旧审计结构可能用字符串表达布尔值，前端需要稳定布尔语义。
 * 输入输出：输入 unknown 与默认值，输出 boolean。
 * 边界条件：仅 true/'true'/1/'1' 视为真，false/'false'/0/'0' 视为假。
 * 异常行为：本函数不抛异常。
 */
function toBooleanValue(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === 1 || value === '1') return true;
  if (value === 'false' || value === 0 || value === '0') return false;
  return fallback;
}

/**
 * 将未知值安全转为字符串数组。
 *
 * 做什么：统一处理 source_keys 字段。
 * 为什么这样做：来源键名必须展示，但后端可能返回空值或单个字符串。
 * 输入输出：输入 unknown，输出字符串数组。
 * 边界条件：数组内 null/undefined 会被过滤。
 * 异常行为：本函数不抛异常。
 */
function toStringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((item) => item !== null && item !== undefined).map((item) => String(item));
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()];
  }
  return [];
}

/**
 * 校验并归一化压缩阶段。
 *
 * 做什么：把未知阶段值转换为前端支持的 CompressionStage。
 * 为什么这样做：组件层不应承担非法枚举兜底逻辑。
 * 输入输出：输入 unknown，输出稳定阶段枚举。
 * 边界条件：未知值兜底为 message_trim，表示最保守的消息裁剪阶段。
 * 异常行为：本函数不抛异常。
 */
function normalizeStage(value: unknown): CompressionStage {
  const raw = toStringValue(value);
  const stages = Object.values(COMPRESSION_STAGE) as CompressionStage[];
  return stages.includes(raw as CompressionStage) ? (raw as CompressionStage) : COMPRESSION_STAGE.MESSAGE_TRIM;
}

/**
 * 校验并归一化压缩作用域。
 *
 * 做什么：把未知作用域值转换为前端支持的 CompressionScope。
 * 为什么这样做：作用域筛选和标签渲染依赖稳定枚举。
 * 输入输出：输入 unknown，输出稳定作用域枚举。
 * 边界条件：未知值兜底为 session_history。
 * 异常行为：本函数不抛异常。
 */
function normalizeScope(value: unknown): CompressionScope {
  const raw = toStringValue(value);
  const scopes = Object.values(COMPRESSION_SCOPE) as CompressionScope[];
  return scopes.includes(raw as CompressionScope) ? (raw as CompressionScope) : COMPRESSION_SCOPE.SESSION_HISTORY;
}

/**
 * 校验并归一化压缩触发原因。
 *
 * 做什么：把未知触发原因转换为前端支持的 CompressionTriggerReason。
 * 为什么这样做：筛选器必须使用稳定枚举，同时详情要能展示可解释文案。
 * 输入输出：输入 unknown，输出稳定触发原因枚举。
 * 边界条件：未知值兜底为 final_prompt_token_over_limit。
 * 异常行为：本函数不抛异常。
 */
function normalizeTriggerReason(value: unknown): CompressionTriggerReason {
  const raw = toStringValue(value);
  const reasons = Object.values(COMPRESSION_TRIGGER_REASON) as CompressionTriggerReason[];
  return reasons.includes(raw as CompressionTriggerReason)
    ? (raw as CompressionTriggerReason)
    : COMPRESSION_TRIGGER_REASON.FINAL_PROMPT_TOKEN_OVER_LIMIT;
}

/**
 * 校验并归一化压缩执行状态。
 *
 * 做什么：把后端状态或布尔成功字段统一转换为 SUCCESS/FAILED/SKIPPED。
 * 为什么这样做：列表展示和本地筛选都依赖稳定基础状态。
 * 输入输出：输入状态值与 is_success，输出 CompressionAuditStatus。
 * 边界条件：未知状态根据 is_success 兜底推导。
 * 异常行为：本函数不抛异常。
 */
function normalizeStatus(value: unknown, isSuccess: boolean): CompressionAuditStatus {
  const raw = toStringValue(value).toUpperCase();
  const statuses = Object.values(COMPRESSION_STATUS) as CompressionAuditStatus[];
  if (statuses.includes(raw as CompressionAuditStatus)) {
    return raw as CompressionAuditStatus;
  }
  return isSuccess ? COMPRESSION_STATUS.SUCCESS : COMPRESSION_STATUS.FAILED;
}

/**
 * 派生压缩审计展示状态。
 *
 * 做什么：从基础状态与阶段值推导“已降级”“强制截断”等前端展示态。
 * 为什么这样做：后端真实状态与产品化诊断标签不同，必须在服务层集中处理。
 * 输入输出：输入基础状态、阶段与最终策略，输出展示状态。
 * 边界条件：失败和跳过优先于降级；强制截断优先级最高。
 * 异常行为：本函数不抛异常。
 */
function deriveDisplayStatus(
  status: CompressionAuditStatus,
  stage: CompressionStage,
  finalStrategy: string,
): CompressionAuditDisplayStatus {
  if (stage === COMPRESSION_STAGE.HARD_TRUNCATION || finalStrategy === COMPRESSION_STAGE.HARD_TRUNCATION) {
    return 'HARD_TRUNCATED';
  }
  if (status === COMPRESSION_STATUS.FAILED || status === COMPRESSION_STATUS.SKIPPED) {
    return status;
  }
  if (
    stage === COMPRESSION_STAGE.HISTORICAL_CONTEXT_MERGE ||
    finalStrategy === COMPRESSION_STAGE.HISTORICAL_CONTEXT_MERGE
  ) {
    return 'DEGRADED';
  }
  return status;
}

/**
 * 将毫秒时间戳转换为 ISO 字符串。
 *
 * 做什么：为缺少 timestamp_iso 的旧结构提供时间兜底。
 * 为什么这样做：列表和详情时间展示不能因为旧字段缺失而崩溃。
 * 输入输出：输入毫秒数和默认字符串，输出 ISO 字符串。
 * 边界条件：非法时间戳返回默认字符串或空字符串。
 * 异常行为：本函数捕获 Date 转换异常并返回兜底值。
 */
function timestampMsToIso(timestampMs: number, fallback = ''): string {
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return fallback;
  try {
    return new Date(timestampMs).toISOString();
  } catch {
    return fallback;
  }
}

/**
 * 从后端 details 字段解析压缩审计 JSON。
 *
 * 做什么：兼容专用接口返回对象和通用审计日志 details 字符串两种来源。
 * 为什么这样做：计划要求后端专用接口未就绪时仍能通过 audit_logs.details 结构化展示。
 * 输入输出：输入未知原始值，输出对象或 null。
 * 边界条件：空字符串、非法 JSON、非对象均返回 null。
 * 异常行为：解析失败不抛出，返回 null 交由上层跳过。
 */
function parsePayloadObject(raw: unknown): Record<string, unknown> | null {
  if (isRecord(raw)) return raw;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * 从任意原始结构中提取压缩审计载荷。
 *
 * 做什么：处理专用接口 item、通用审计 log、嵌套 payload/details 等不同包装。
 * 为什么这样做：兼容逻辑必须集中在服务层，组件只消费稳定结构。
 * 输入输出：输入 unknown，输出可解析载荷与外层日志元数据。
 * 边界条件：不是压缩审计记录时返回 null。
 * 异常行为：本函数不抛异常。
 */
function extractCompressionPayload(raw: unknown): { payload: Record<string, unknown>; log?: RawAuditLogEnvelope } | null {
  if (!isRecord(raw)) return null;

  if (raw.details !== undefined) {
    if (raw.action_type && raw.action_type !== COMPRESSION_AUDIT_ACTION_TYPE) return null;
    const payload = parsePayloadObject(raw.details);
    return payload ? { payload, log: raw as RawAuditLogEnvelope } : null;
  }

  if (isRecord(raw.payload)) {
    return { payload: raw.payload };
  }

  if (raw.schema_version === COMPRESSION_AUDIT_SCHEMA_VERSION || raw.trace_id || raw.stage) {
    return { payload: raw };
  }

  return null;
}

/**
 * 归一化单条压缩回放事件。
 *
 * 做什么：把后端压缩审计载荷转换为详情时间线事件。
 * 为什么这样做：时间线、阶段详情和列表项应使用同一字段解析口径。
 * 输入输出：输入载荷对象与可选外层日志，输出 CompressionReplayEvent。
 * 边界条件：缺失字段使用安全兜底；preview 仅使用后端已脱敏文本。
 * 异常行为：本函数不抛异常。
 */
function normalizeCompressionReplayEvent(
  payload: Record<string, unknown>,
  log?: RawAuditLogEnvelope,
): CompressionReplayEvent {
  const stage = normalizeStage(payload.stage);
  const scope = normalizeScope(payload.scope);
  const triggerReason = normalizeTriggerReason(payload.trigger_reason);
  const rawTokens = toNumberValue(payload.raw_tokens);
  const finalTokens = toNumberValue(payload.final_tokens);
  const isSuccess = toBooleanValue(payload.is_success, toStringValue(log?.status) === COMPRESSION_STATUS.SUCCESS);
  const status = normalizeStatus(log?.status, isSuccess);
  const timestampMs = toNumberValue(payload.timestamp_ms);
  const timestampIso = toStringValue(payload.timestamp_iso, timestampMsToIso(timestampMs, toStringValue(log?.timestamp)));
  const finalStrategy = toStringValue(payload.final_strategy, stage);

  return {
    schema_version: toStringValue(payload.schema_version, COMPRESSION_AUDIT_SCHEMA_VERSION),
    replay_snapshot_id: toStringValue(payload.replay_snapshot_id),
    trace_id: toStringValue(payload.trace_id, toStringValue(log?.trace_id)),
    session_id: toStringValue(payload.session_id),
    message_id: toStringValue(payload.message_id),
    stage,
    scope,
    trigger_reason: triggerReason,
    source_keys: toStringArray(payload.source_keys),
    raw_tokens: rawTokens,
    after_trim_tokens: toNumberValue(payload.after_trim_tokens),
    after_summary_tokens: toNumberValue(payload.after_summary_tokens),
    final_tokens: finalTokens,
    stage_compression_ratio: toNumberValue(payload.stage_compression_ratio),
    total_compression_ratio: toNumberValue(payload.total_compression_ratio),
    model_provider: toStringValue(payload.model_provider),
    model_base_url: toStringValue(payload.model_base_url),
    model_id: toStringValue(payload.model_id),
    preview_before: toStringValue(payload.preview_before),
    preview_after: toStringValue(payload.preview_after),
    is_success: isSuccess,
    failure_reason: toStringValue(payload.failure_reason, toStringValue(log?.error_msg)),
    timestamp_ms: timestampMs,
    timestamp_iso: timestampIso,
    display_status: deriveDisplayStatus(status, stage, finalStrategy),
  };
}

/**
 * 归一化压缩审计列表项。
 *
 * 做什么：把专用接口 item 或通用 audit_logs.details 转为列表行数据。
 * 为什么这样做：列表组件不应关心后端包装格式，也不应自行解析 JSON。
 * 输入输出：输入 unknown，输出 CompressionAuditListItem 或 null。
 * 边界条件：无法提取压缩 payload 时返回 null。
 * 异常行为：本函数不抛异常。
 */
export function normalizeCompressionAudit(raw: unknown): CompressionAuditListItem | null {
  const extracted = extractCompressionPayload(raw);
  if (!extracted) return null;

  const event = normalizeCompressionReplayEvent(extracted.payload, extracted.log);
  const isSuccess = event.is_success;
  const status = normalizeStatus(extracted.log?.status, isSuccess);
  const id = toStringValue(extracted.log?.id, event.replay_snapshot_id || `${event.trace_id}-${event.timestamp_ms}`);
  const finalStrategy = toStringValue(extracted.payload.final_strategy, event.stage);

  return {
    schema_version: event.schema_version,
    id,
    trace_id: toStringValue(extracted.payload.trace_id, toStringValue(extracted.log?.trace_id)),
    session_id: toStringValue(extracted.payload.session_id),
    message_id: toStringValue(extracted.payload.message_id),
    replay_snapshot_id: event.replay_snapshot_id,
    stage: event.stage,
    scope: event.scope,
    trigger_reason: event.trigger_reason,
    raw_tokens: event.raw_tokens,
    final_tokens: event.final_tokens,
    total_compression_ratio: event.total_compression_ratio,
    status,
    display_status: deriveDisplayStatus(status, event.stage, finalStrategy),
    final_strategy: finalStrategy,
    failure_reason: event.failure_reason,
    timestamp: event.timestamp_iso,
    timestamp_ms: event.timestamp_ms,
  };
}

/**
 * 归一化压缩 Span。
 *
 * 做什么：把回放接口中的 spans 数组转换为稳定前端结构。
 * 为什么这样做：详情页保留耗时信息，Trace 跳转可查看完整 Span 树。
 * 输入输出：输入 unknown，输出 CompressionReplaySpan 或 null。
 * 边界条件：非法 attributes 兜底为空对象。
 * 异常行为：本函数不抛异常。
 */
function normalizeReplaySpan(raw: unknown): CompressionReplaySpan | null {
  if (!isRecord(raw)) return null;
  const attributes = isRecord(raw.attributes) ? raw.attributes : {};
  return {
    span_id: toStringValue(raw.span_id),
    name: toStringValue(raw.name),
    service: toStringValue(raw.service),
    duration_ms: toNumberValue(raw.duration_ms),
    status: toStringValue(raw.status),
    start_time: raw.start_time === null || raw.start_time === undefined ? null : toStringValue(raw.start_time),
    end_time: raw.end_time === null || raw.end_time === undefined ? null : toStringValue(raw.end_time),
    attributes,
  };
}

/**
 * 构建压缩回放总览摘要。
 *
 * 做什么：从回放接口 summary 与事件数组中生成前端稳定摘要。
 * 为什么这样做：后端 summary 当前不包含 is_success/failure_reason，前端需要集中补齐。
 * 输入输出：输入原始 summary 与事件数组，输出 CompressionReplaySummary。
 * 边界条件：无事件时返回空摘要结构。
 * 异常行为：本函数不抛异常。
 */
function buildReplaySummary(rawSummary: unknown, events: CompressionReplayEvent[]) {
  const summary = isRecord(rawSummary) ? rawSummary : {};
  const lastEvent = events[events.length - 1];
  const failedEvent = events.find((event) => !event.is_success || event.failure_reason);
  const finalStrategy = toStringValue(summary.final_strategy, lastEvent?.stage ?? '');
  const displayStatus = lastEvent
    ? deriveDisplayStatus(lastEvent.is_success ? COMPRESSION_STATUS.SUCCESS : COMPRESSION_STATUS.FAILED, lastEvent.stage, finalStrategy)
    : COMPRESSION_STATUS.SKIPPED;

  return {
    schema_version: COMPRESSION_REPLAY_SCHEMA_VERSION,
    raw_tokens: toNumberValue(summary.raw_tokens, events.reduce((total, event) => total + event.raw_tokens, 0)),
    final_tokens: toNumberValue(summary.final_tokens, lastEvent?.final_tokens ?? 0),
    total_compression_ratio: toNumberValue(summary.total_compression_ratio, lastEvent?.total_compression_ratio ?? 0),
    final_strategy: finalStrategy,
    is_success: events.length > 0 ? events.every((event) => event.is_success) : false,
    failure_reason: failedEvent?.failure_reason ?? '',
    started_at: events[0]?.timestamp_iso ?? '',
    display_status: displayStatus,
  };
}

/**
 * 归一化压缩回放详情。
 *
 * 做什么：把后端 replay 响应或兜底事件数组转换为详情抽屉可消费结构。
 * 为什么这样做：组件必须只负责展示，不负责拼接事件、快照与 summary。
 * 输入输出：输入 unknown，输出 CompressionReplayDetail。
 * 边界条件：空响应返回空事件详情，但保留 trace_id 兜底。
 * 异常行为：本函数不抛异常。
 */
export function normalizeCompressionReplay(raw: unknown, fallbackTraceId = ''): CompressionReplayDetail {
  const data = isRecord(raw) ? raw : {};
  const rawEvents = Array.isArray(data.events) ? data.events : [];
  const events = rawEvents
    .map((item) => {
      const extracted = extractCompressionPayload(item);
      return extracted ? normalizeCompressionReplayEvent(extracted.payload, extracted.log) : null;
    })
    .filter((item): item is CompressionReplayEvent => item !== null)
    .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
  const spans = (Array.isArray(data.spans) ? data.spans : [])
    .map(normalizeReplaySpan)
    .filter((item): item is CompressionReplaySpan => item !== null);

  return {
    schema_version: COMPRESSION_REPLAY_SCHEMA_VERSION,
    trace_id: toStringValue(data.trace_id, fallbackTraceId),
    session_id: toStringValue(data.session_id, events[0]?.session_id ?? ''),
    message_id: toStringValue(data.message_id, events[0]?.message_id ?? ''),
    summary: buildReplaySummary(data.summary, events),
    events,
    spans,
  };
}

/**
 * 读取标准 API 响应数据。
 *
 * 做什么：统一解析 FastAPI ResponseModel 包装，并对非 0 code 抛出可解释错误。
 * 为什么这样做：服务层调用方只应处理成功 data 或捕获错误摘要。
 * 输入输出：输入 fetch Response，输出 data。
 * 边界条件：非 JSON 响应会抛出统一错误。
 * 异常行为：HTTP 非 2xx 或 code 非 0 时抛 Error。
 */
async function readApiData(response: Response, fallbackErrorMessage: string): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`${fallbackErrorMessage}: HTTP ${response.status}`);
  }
  const json = (await response.json()) as ApiEnvelope;
  if (typeof json.code === 'number' && json.code !== 0) {
    throw new Error(json.msg || fallbackErrorMessage);
  }
  return json.data ?? json;
}

/**
 * 判断是否启用了需要本地二次过滤的条件。
 *
 * 做什么：识别专用接口当前不能直接处理的筛选项。
 * 为什么这样做：后端当前只支持 status/trace_id，其他筛选需要前端在服务层集中兼容。
 * 输入输出：输入筛选对象，输出 boolean。
 * 边界条件：空字符串视为未启用。
 * 异常行为：本函数不抛异常。
 */
function hasClientSideFilters(filters: CompressionAuditFilters): boolean {
  return CLIENT_FILTER_KEYS.some((key) => Boolean(filters[key]));
}

/**
 * 应用压缩审计本地筛选。
 *
 * 做什么：补齐阶段、作用域、触发原因、时间范围、SessionID 等筛选能力。
 * 为什么这样做：计划要求这些筛选必须可用，而后端专用接口当前只支持部分字段。
 * 输入输出：输入列表项和筛选条件，输出过滤后的列表项。
 * 边界条件：display_status 支持派生状态；trace_id/session_id 均精确匹配。
 * 异常行为：本函数不抛异常。
 */
function applyCompressionAuditFilters(
  items: CompressionAuditListItem[],
  filters: CompressionAuditFilters,
): CompressionAuditListItem[] {
  const startTime = filters.start_time ? new Date(filters.start_time).getTime() : 0;
  const endTime = filters.end_time ? new Date(filters.end_time).getTime() : 0;

  return items.filter((item) => {
    if (filters.stage && item.stage !== filters.stage) return false;
    if (filters.scope && item.scope !== filters.scope) return false;
    if (filters.trigger_reason && item.trigger_reason !== filters.trigger_reason) return false;
    if (filters.status && item.display_status !== filters.status && item.status !== filters.status) return false;
    if (filters.trace_id && item.trace_id !== filters.trace_id.trim()) return false;
    if (filters.session_id && item.session_id !== filters.session_id.trim()) return false;
    if (startTime && item.timestamp_ms < startTime) return false;
    if (endTime && item.timestamp_ms > endTime) return false;
    return true;
  });
}

/**
 * 从专用压缩审计接口拉取列表。
 *
 * 做什么：优先消费 /compression_audits 专用接口。
 * 为什么这样做：专用接口已由后端聚合 details，字段更接近前端目标结构。
 * 输入输出：输入查询参数，输出原始 data。
 * 边界条件：本地筛选启用时扩大拉取范围再分页。
 * 异常行为：接口不可用或响应异常时抛 Error，由上层决定是否兜底到 audit_logs。
 */
async function fetchCompressionAuditsFromDedicatedApi(params: FetchCompressionAuditsParams): Promise<unknown> {
  const query = new URLSearchParams();
  const needClientFilter = hasClientSideFilters(params.filters);
  const limit = needClientFilter ? FALLBACK_AUDIT_LOG_LIMIT : params.pageSize;
  const offset = needClientFilter ? 0 : (params.page - 1) * params.pageSize;
  query.set('limit', String(limit));
  query.set('offset', String(offset));
  if (params.filters.trace_id?.trim()) query.set('trace_id', params.filters.trace_id.trim());
  if (params.filters.status && Object.values(COMPRESSION_STATUS).includes(params.filters.status as CompressionAuditStatus)) {
    query.set('status', params.filters.status);
  }

  const response = await fetch(`${TELEMETRY_BASE}/compression_audits?${query.toString()}`, {
    signal: AbortSignal.timeout(COMPRESSION_AUDIT_REQUEST_TIMEOUT_MS),
  });
  return readApiData(response, '压缩审计读取失败');
}

/**
 * 从通用审计日志接口兜底拉取压缩审计列表。
 *
 * 做什么：在专用接口不可用时读取 audit_logs 中 CONTEXT_COMPRESSION 记录。
 * 为什么这样做：计划要求后端仍通过 details 字符串返回时，前端也要能解析与渲染。
 * 输入输出：输入查询参数，输出原始 logs 数据。
 * 边界条件：兜底路径固定扩大 limit，随后由前端本地筛选分页。
 * 异常行为：接口异常时抛 Error。
 */
async function fetchCompressionAuditsFromAuditLogs(params: FetchCompressionAuditsParams): Promise<unknown> {
  const query = new URLSearchParams();
  query.set('limit', String(FALLBACK_AUDIT_LOG_LIMIT));
  query.set('offset', '0');
  query.set('action_type', COMPRESSION_AUDIT_ACTION_TYPE);
  if (params.filters.trace_id?.trim()) query.set('trace_id', params.filters.trace_id.trim());
  if (params.filters.status && Object.values(COMPRESSION_STATUS).includes(params.filters.status as CompressionAuditStatus)) {
    query.set('status', params.filters.status);
  }

  const response = await fetch(`${TELEMETRY_BASE}/audit_logs?${query.toString()}`, {
    signal: AbortSignal.timeout(COMPRESSION_AUDIT_REQUEST_TIMEOUT_MS),
  });
  return readApiData(response, '通用审计日志读取失败');
}

/**
 * 从原始列表响应中提取数组和总数。
 *
 * 做什么：兼容 {items,total}、{logs,total}、数组三类返回形态。
 * 为什么这样做：专用接口和兜底接口包装不同，必须在服务层统一。
 * 输入输出：输入 unknown，输出 rawItems 和 total。
 * 边界条件：未知结构返回空数组。
 * 异常行为：本函数不抛异常。
 */
function extractListPayload(rawData: unknown): { rawItems: unknown[]; total: number } {
  if (Array.isArray(rawData)) {
    return { rawItems: rawData, total: rawData.length };
  }
  if (!isRecord(rawData)) {
    return { rawItems: [], total: 0 };
  }
  if (Array.isArray(rawData.items)) {
    return { rawItems: rawData.items, total: toNumberValue(rawData.total, rawData.items.length) };
  }
  if (Array.isArray(rawData.logs)) {
    return { rawItems: rawData.logs, total: toNumberValue(rawData.total, rawData.logs.length) };
  }
  return { rawItems: [], total: 0 };
}

/**
 * 拉取压缩审计列表。
 *
 * 做什么：读取压缩审计列表，完成接口兜底、JSON 解析、本地筛选与分页。
 * 为什么这样做：组件层必须获得稳定可展示的数据，而不是处理后端多形态响应。
 * 输入输出：输入分页和筛选参数，输出归一化分页结果。
 * 边界条件：专用接口失败时自动降级到通用 audit_logs；两者都失败才抛出错误。
 * 异常行为：所有请求失败时抛 Error，调用方展示“压缩审计读取失败”。
 */
export async function fetchCompressionAudits(
  params: FetchCompressionAuditsParams,
): Promise<CompressionAuditListResponse> {
  let rawData: unknown;
  try {
    rawData = await fetchCompressionAuditsFromDedicatedApi(params);
  } catch {
    rawData = await fetchCompressionAuditsFromAuditLogs(params);
  }

  const { rawItems, total } = extractListPayload(rawData);
  const normalizedItems = rawItems
    .map(normalizeCompressionAudit)
    .filter((item): item is CompressionAuditListItem => item !== null)
    .sort((left, right) => right.timestamp_ms - left.timestamp_ms);
  const filteredItems = applyCompressionAuditFilters(normalizedItems, params.filters);
  const needClientFilter = hasClientSideFilters(params.filters) || Boolean(params.filters.status?.startsWith('HARD_')) || params.filters.status === 'DEGRADED';

  if (!needClientFilter) {
    return {
      items: filteredItems,
      total: total || filteredItems.length,
    };
  }

  const start = (params.page - 1) * params.pageSize;
  return {
    items: filteredItems.slice(start, start + params.pageSize),
    total: filteredItems.length,
  };
}

/**
 * 拉取压缩回放详情。
 *
 * 做什么：优先调用 /compression_replays/{trace_id}，并归一化为详情抽屉结构。
 * 为什么这样做：回放页面需要一次性获得总览、时间线、阶段详情与 Span 摘要。
 * 输入输出：输入 traceId，输出 CompressionReplayDetail。
 * 边界条件：traceId 为空时直接抛出可解释错误；接口返回空事件时保留空态结构。
 * 异常行为：请求失败时抛 Error，调用方展示“压缩回放加载失败”。
 */
export async function fetchCompressionReplay(traceId: string): Promise<CompressionReplayDetail> {
  const normalizedTraceId = traceId.trim();
  if (!normalizedTraceId) {
    throw new Error('TraceID 不能为空');
  }

  const response = await fetch(`${TELEMETRY_BASE}/compression_replays/${encodeURIComponent(normalizedTraceId)}`, {
    signal: AbortSignal.timeout(COMPRESSION_AUDIT_REQUEST_TIMEOUT_MS),
  });
  const data = await readApiData(response, '压缩回放加载失败');
  return normalizeCompressionReplay(data, normalizedTraceId);
}
