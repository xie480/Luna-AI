/**
 * Luna AI 前端错误日志持久化服务
 *
 * 做什么：将前端捕获的异常信息通过 HTTP POST 上报到后端 API，
 *        由后端持久化到 PostgreSQL error_logs 表。
 * 为什么这样做：所有前端异常必须持久化到数据库，而非仅存于内存。
 * 边界条件：
 *   - 后端不可用时静默降级，不阻塞前端主流程
 *   - 自动从 systemStore 获取当前 TraceID 用于链路关联
 * 异常行为：
 *   - 上报失败仅产生控制台警告，不抛异常影响用户
 */
import { generateId } from '../../shared/utils/snowflake';
import { useSystemStore } from '../stores/systemStore';

/** 错误级别枚举 */
export type ErrorLogLevel = 'ERROR' | 'WARN' | 'CRITICAL';

/** 错误日志上报请求体结构 */
export interface ErrorLogReport {
  level: ErrorLogLevel;
  source: string;
  message: string;
  detail: string;
  trace_id: string;
}

/** 错误日志上报响应体结构 */
interface ErrorLogResponse {
  code: number;
  msg: string;
  id: string;
}

import { AI_SERVICE_BASE_URL } from '../appConfig';

/** 后端 API 基础地址（端口从 .env 文件统一读取） */
const BACKEND_BASE = AI_SERVICE_BASE_URL;

/**
 * 上报错误日志到后端 API 进行持久化
 *
 * 做什么：将错误日志通过 HTTP POST 发送到 /api/error_logs 端点，
 *        由后端写入 PostgreSQL error_logs 表。
 * 为什么这样做：确保所有异常有持久化记录，支持后续审计和排查。
 * 输入：
 *   - report: ErrorLogReport 错误日志信息
 * 输出：Promise<boolean> 上报是否成功
 * 边界条件：
 *   - 后端不可用时静默降级，返回 false 但不抛异常
 *   - 自动使用 systemStore 中的 currentTraceID 作为 trace_id
 */
export async function reportErrorLog(report: ErrorLogReport): Promise<boolean> {
  // 从 store 获取当前 TraceID，如果没有则自动生成
  const systemStore = useSystemStore.getState();
  const traceId = report.trace_id || systemStore.currentTraceID || generateId();

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/error_logs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': traceId,
      },
      body: JSON.stringify({
        ...report,
        trace_id: traceId,
      }),
    });

    if (resp.ok) {
      const result: ErrorLogResponse = await resp.json();
      if (result.code === 0) {
        // 上报成功
        return true;
      }
      // 后端返回业务错误码，记录警告
      console.warn(`[ErrorLogService] 后端返回错误: code=${result.code}, msg=${result.msg}`);
      return false;
    }

    // HTTP 错误，记录状态码
    console.warn(`[ErrorLogService] HTTP ${resp.status} 上报错误日志失败`);
    return false;
  } catch (err) {
    // 网络等异常：静默降级，不阻塞主流程
    console.warn('[ErrorLogService] 上报错误日志失败（后端不可用，静默降级）:', err);
    return false;
  }
}

/**
 * 便捷方法：快速上报一条 ERROR 级别错误
 *
 * 做什么：封装 reportErrorLog，简化调用方代码。
 * 为什么这样做：大多数场景只需指定 source 和 message 即可。
 * 输入：
 *   - source: 错误来源标识
 *   - message: 错误摘要信息
 *   - detail: 详细错误信息（可选，如 stack trace）
 * 输出：Promise<boolean>
 */
export async function reportError(
  source: string,
  message: string,
  detail: string = '',
): Promise<boolean> {
  const traceId = useSystemStore.getState().currentTraceID || generateId();

  return reportErrorLog({
    level: 'ERROR',
    source,
    message,
    detail,
    trace_id: traceId,
  });
}

/**
 * 便捷方法：快速上报一条 CRITICAL 级别错误
 *
 * 做什么：封装 reportErrorLog，适用于致命错误场景。
 */
export async function reportCritical(
  source: string,
  message: string,
  detail: string = '',
): Promise<boolean> {
  const traceId = useSystemStore.getState().currentTraceID || generateId();

  return reportErrorLog({
    level: 'CRITICAL',
    source,
    message,
    detail,
    trace_id: traceId,
  });
}

/**
 * 便捷方法：快速上报一条 WARN 级别警告
 */
export async function reportWarning(
  source: string,
  message: string,
  detail: string = '',
): Promise<boolean> {
  const traceId = useSystemStore.getState().currentTraceID || generateId();

  return reportErrorLog({
    level: 'WARN',
    source,
    message,
    detail,
    trace_id: traceId,
  });
}
