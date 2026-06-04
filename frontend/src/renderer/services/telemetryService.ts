import { AI_SERVICE_BASE_URL } from '../appConfig';
import { TelemetrySpan, AuditLogEntry, MetricsDataPoint } from '../stores/telemetryStore';
import { useSystemStore } from '../stores/systemStore';

/** 遥测 API 基础 URL（端口从 .env 文件统一读取） */
const TELEMETRY_BASE = `${AI_SERVICE_BASE_URL}/api/v1/telemetry`;

/**
 * 查询链路 Spans（支持分页和按 TraceID 筛选）
 */
export async function fetchTraces(params: {
  page: number;
  pageSize: number;
  trace_id?: string;
}): Promise<{ data: TelemetrySpan[]; total: number }> {
  const query = new URLSearchParams();
  query.set('limit', String(params.pageSize));
  query.set('offset', String((params.page - 1) * params.pageSize));
  if (params.trace_id) query.set('trace_id', params.trace_id);

  const response = await fetch(`${TELEMETRY_BASE}/traces?${query.toString()}`, {
    signal: AbortSignal.timeout(5000),
  });

  if (!response.ok) {
    throw new Error(`获取链路追踪失败: ${response.status}`);
  }

  const json = await response.json();
  return {
    data: (Array.isArray(json.data?.spans) ? json.data.spans : []) as TelemetrySpan[],
    total: typeof json.data?.total === 'number' ? json.data.total : 0,
  };
}

/**
 * 查询审计日志（支持分页和筛选）
 * 返回值中的 data 字段确保为数组，防止后端返回 null 导致前端 .map() 崩溃
 */
export async function fetchAuditLogs(params: {
  page: number;
  pageSize: number;
  action_type?: string;
  status?: string;
  start_time?: string;
  end_time?: string;
}): Promise<{ data: AuditLogEntry[]; total: number }> {
  const query = new URLSearchParams();
  query.set('limit', String(params.pageSize));
  query.set('offset', String((params.page - 1) * params.pageSize));
  if (params.action_type) query.set('action_type', params.action_type);
  if (params.status) query.set('status', params.status);
  if (params.start_time) query.set('start_time', params.start_time);
  if (params.end_time) query.set('end_time', params.end_time);

  const response = await fetch(`${TELEMETRY_BASE}/audit_logs?${query.toString()}`, {
    signal: AbortSignal.timeout(5000),
  });

  if (!response.ok) {
    throw new Error(`获取审计日志失败: ${response.status}`);
  }

  const json = await response.json();
  return {
    data: (Array.isArray(json.data) ? json.data : []) as AuditLogEntry[],
    total: typeof json.total === 'number' ? json.total : 0,
  };
}

/**
 * 拉取监控指标数据
 */
export async function fetchMetrics(range: '1h' | '6h' | '24h'): Promise<MetricsDataPoint[]> {
  const response = await fetch(`${TELEMETRY_BASE}/metrics?range=${range}`, {
    signal: AbortSignal.timeout(5000),
  });

  if (!response.ok) {
    throw new Error(`获取监控指标失败: ${response.status}`);
  }

  const json = await response.json();
  return Array.isArray(json.data) ? json.data : [];
}

/**
 * 上传前端异常日志到后端
 * 每积累 10 条或每 30 秒触发一次上报
 */
export async function uploadFrontendErrors(): Promise<void> {
  const errors = useSystemStore.getState().frontendErrors;
  if (errors.length === 0) return;

  try {
    const response = await fetch(`${TELEMETRY_BASE}/frontend_errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        errors: errors.slice(-10), // 每次最多上报 10 条
        client_timestamp: Date.now(),
        app_version: '__APP_VERSION__',
      }),
    });

    if (response.ok) {
      // 上报成功后清除已上报的部分
      useSystemStore.getState().clearFrontendErrors();
    }
  } catch (err) {
    // 上报失败不阻塞主流程，仅记录日志
    console.warn('[Telemetry] 前端异常上报失败:', err);
  }
}

/**
 * 定期上报定时器
 */
let uploadTimer: ReturnType<typeof setInterval> | null = null;

export function startErrorUploadTimer(intervalMs: number = 30000): void {
  if (uploadTimer) clearInterval(uploadTimer);
  uploadTimer = setInterval(uploadFrontendErrors, intervalMs);
}

export function stopErrorUploadTimer(): void {
  if (uploadTimer) {
    clearInterval(uploadTimer);
    uploadTimer = null;
  }
}
