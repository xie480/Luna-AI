import React, { useCallback, useEffect } from 'react';
import {
  COMPRESSION_SCOPE,
  COMPRESSION_SCOPE_LABEL,
  COMPRESSION_STAGE,
  COMPRESSION_STAGE_LABEL,
  COMPRESSION_STATUS,
  COMPRESSION_STATUS_LABEL,
  COMPRESSION_TRIGGER_REASON,
  COMPRESSION_TRIGGER_REASON_LABEL,
} from '../../../../shared/enum';
import { fetchCompressionAudits, fetchCompressionReplay } from '../../../services/compressionAuditService';
import { useTelemetryStore } from '../../../stores/telemetryStore';
import type {
  CompressionAuditDisplayStatus,
  CompressionScope,
  CompressionStage,
  CompressionTriggerReason,
} from '../../../types/compressionAudit';
import CompressionReplayDrawer from './CompressionReplayDrawer';

/** 压缩审计状态筛选选项。 */
const COMPRESSION_DISPLAY_STATUS_OPTIONS: CompressionAuditDisplayStatus[] = [
  COMPRESSION_STATUS.SUCCESS,
  COMPRESSION_STATUS.FAILED,
  COMPRESSION_STATUS.SKIPPED,
  'DEGRADED',
  'HARD_TRUNCATED',
];

/**
 * 将比例转换为百分比文本。
 *
 * 做什么：统一格式化列表中的总压缩率。
 * 为什么这样做：后端返回 after/before 小数，表格需要展示为直观百分比。
 * 输入输出：输入数字比例，输出百分比字符串。
 * 边界条件：非法数字显示为 0.0%。
 * 异常行为：无。
 */
function formatRatio(ratio: number): string {
  if (!Number.isFinite(ratio)) return '0.0%';
  return `${(ratio * 100).toFixed(1)}%`;
}

/**
 * 根据压缩率和状态返回展示等级。
 *
 * 做什么：为总压缩率单元格生成低/中/高/强制截断等级样式。
 * 为什么这样做：计划要求压缩率在颜色上区分强度与强制截断。
 * 输入输出：输入比例与展示状态，输出 CSS 等级名。
 * 边界条件：强制截断优先级最高。
 * 异常行为：无。
 */
function getRatioTone(ratio: number, status: CompressionAuditDisplayStatus): 'low' | 'medium' | 'high' | 'danger' {
  if (status === 'HARD_TRUNCATED') return 'danger';
  if (ratio <= 0.5) return 'high';
  if (ratio <= 0.8) return 'medium';
  return 'low';
}

/**
 * 格式化时间字段。
 *
 * 做什么：将后端 ISO 时间转为本地可读时间。
 * 为什么这样做：诊断面板面向本地桌面使用，开发者按本地时区排查更直观。
 * 输入输出：输入 ISO 字符串，输出本地时间字符串。
 * 边界条件：空值展示为“未记录”；非法时间显示原始文本。
 * 异常行为：无。
 */
function formatTime(value: string): string {
  if (!value) return '未记录';
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return value;
  return time.toLocaleString();
}

/**
 * 压缩审计列表页面。
 *
 * 做什么：在诊断面板中展示压缩审计列表、筛选、分页，并提供回放详情入口。
 * 为什么这样做：计划要求开发者能快速定位触发压缩的请求，并从列表追溯到回放详情。
 * 输入输出：无 props；通过 telemetryStore 管理筛选、分页、列表和抽屉状态。
 * 边界条件：接口不可用、列表为空、筛选无命中、回放失败均提供明确状态。
 * 异常行为：请求异常被捕获并写入 Store，不产生未捕获 Promise。
 */
const CompressionAuditViewer: React.FC = () => {
  const {
    compressionAudits,
    compressionAuditTotal,
    compressionAuditPage,
    compressionAuditPageSize,
    compressionAuditFilters,
    isLoadingCompressionAudits,
    compressionAuditError,
    setCompressionAudits,
    setCompressionAuditFilters,
    resetCompressionAuditFilters,
    setCompressionAuditPage,
    setLoadingCompressionAudits,
    setCompressionAuditError,
    setSelectedCompressionReplay,
    setCompressionReplayOpen,
    setLoadingCompressionReplay,
    setCompressionReplayError,
    setCurrentTraceId,
    setActiveDebugTab,
  } = useTelemetryStore();

  const loadAudits = useCallback(async () => {
    setLoadingCompressionAudits(true);
    setCompressionAuditError('');
    try {
      const result = await fetchCompressionAudits({
        page: compressionAuditPage,
        pageSize: compressionAuditPageSize,
        filters: compressionAuditFilters,
      });
      setCompressionAudits(result.items, result.total);
    } catch (error) {
      const message = error instanceof Error ? error.message : '压缩审计读取失败，请稍后重试';
      setCompressionAudits([], 0);
      setCompressionAuditError(message);
    } finally {
      setLoadingCompressionAudits(false);
    }
  }, [
    compressionAuditFilters,
    compressionAuditPage,
    compressionAuditPageSize,
    setCompressionAuditError,
    setCompressionAudits,
    setLoadingCompressionAudits,
  ]);

  useEffect(() => {
    loadAudits();
  }, [loadAudits]);

  const openReplay = useCallback(async (traceId: string) => {
    setCompressionReplayOpen(true);
    setLoadingCompressionReplay(true);
    setCompressionReplayError('');
    setSelectedCompressionReplay(null);
    try {
      const detail = await fetchCompressionReplay(traceId);
      setSelectedCompressionReplay(detail);
    } catch (error) {
      const message = error instanceof Error ? error.message : '压缩回放加载失败';
      setCompressionReplayError(message);
    } finally {
      setLoadingCompressionReplay(false);
    }
  }, [setCompressionReplayError, setCompressionReplayOpen, setLoadingCompressionReplay, setSelectedCompressionReplay]);

  const jumpToTrace = useCallback((traceId: string) => {
    setCurrentTraceId(traceId);
    setActiveDebugTab('traces');
  }, [setActiveDebugTab, setCurrentTraceId]);

  const totalPages = Math.max(1, Math.ceil(compressionAuditTotal / compressionAuditPageSize));
  const isFiltered = Object.values(compressionAuditFilters).some(Boolean);
  const isEmpty = compressionAudits.length === 0 && !isLoadingCompressionAudits && !compressionAuditError;

  return (
    <div className="compression-audit-viewer">
      <div className="compression-audit-toolbar">
        <div className="compression-audit-filters">
          <input
            type="datetime-local"
            value={compressionAuditFilters.start_time || ''}
            onChange={(event) => setCompressionAuditFilters({ start_time: event.target.value || undefined })}
            title="开始时间"
          />
          <input
            type="datetime-local"
            value={compressionAuditFilters.end_time || ''}
            onChange={(event) => setCompressionAuditFilters({ end_time: event.target.value || undefined })}
            title="结束时间"
          />
          <select
            value={compressionAuditFilters.stage || ''}
            onChange={(event) => setCompressionAuditFilters({ stage: (event.target.value || undefined) as CompressionStage | undefined })}
          >
            <option value="">所有阶段</option>
            {Object.values(COMPRESSION_STAGE).map((stage) => (
              <option key={stage} value={stage}>{COMPRESSION_STAGE_LABEL[stage]}</option>
            ))}
          </select>
          <select
            value={compressionAuditFilters.scope || ''}
            onChange={(event) => setCompressionAuditFilters({ scope: (event.target.value || undefined) as CompressionScope | undefined })}
          >
            <option value="">所有作用域</option>
            {Object.values(COMPRESSION_SCOPE).map((scope) => (
              <option key={scope} value={scope}>{COMPRESSION_SCOPE_LABEL[scope]}</option>
            ))}
          </select>
          <select
            value={compressionAuditFilters.status || ''}
            onChange={(event) => setCompressionAuditFilters({ status: (event.target.value || undefined) as CompressionAuditDisplayStatus | undefined })}
          >
            <option value="">所有状态</option>
            {COMPRESSION_DISPLAY_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>{COMPRESSION_STATUS_LABEL[status]}</option>
            ))}
          </select>
          <select
            value={compressionAuditFilters.trigger_reason || ''}
            onChange={(event) => setCompressionAuditFilters({ trigger_reason: (event.target.value || undefined) as CompressionTriggerReason | undefined })}
          >
            <option value="">所有触发原因</option>
            {Object.values(COMPRESSION_TRIGGER_REASON).map((reason) => (
              <option key={reason} value={reason}>{COMPRESSION_TRIGGER_REASON_LABEL[reason]}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="TraceID 精确检索"
            value={compressionAuditFilters.trace_id || ''}
            onChange={(event) => setCompressionAuditFilters({ trace_id: event.target.value || undefined })}
          />
          <input
            type="text"
            placeholder="SessionID 精确检索"
            value={compressionAuditFilters.session_id || ''}
            onChange={(event) => setCompressionAuditFilters({ session_id: event.target.value || undefined })}
          />
        </div>
        <div className="compression-audit-actions">
          <button onClick={loadAudits} disabled={isLoadingCompressionAudits}>
            {isLoadingCompressionAudits ? '刷新中...' : '刷新'}
          </button>
          <button onClick={resetCompressionAuditFilters} disabled={isLoadingCompressionAudits}>清空筛选</button>
        </div>
      </div>

      {compressionAuditError ? (
        <div className="compression-audit-state error">
          <h4>压缩审计读取失败，请稍后重试</h4>
          <p>{compressionAuditError}</p>
          <button onClick={loadAudits}>重试</button>
        </div>
      ) : isLoadingCompressionAudits && compressionAudits.length === 0 ? (
        <div className="compression-audit-loading">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="compression-skeleton row" />
          ))}
        </div>
      ) : isEmpty ? (
        <div className="compression-audit-state empty">
          {isFiltered ? '当前筛选条件下暂无命中记录' : '暂无压缩治理记录'}
        </div>
      ) : (
        <div className="compression-audit-table-wrap">
          <table className="audit-table compression-audit-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>TraceID</th>
                <th>SessionID</th>
                <th>消息 ID</th>
                <th>阶段</th>
                <th>作用域</th>
                <th>触发原因</th>
                <th>原始 Token</th>
                <th>最终 Token</th>
                <th>总压缩率</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {compressionAudits.map((item) => {
                const ratioTone = getRatioTone(item.total_compression_ratio, item.display_status);
                return (
                  <tr key={item.id} className={`compression-row status-${item.display_status.toLowerCase()}`}>
                    <td>{formatTime(item.timestamp)}</td>
                    <td>
                      <button className="trace-link" onClick={() => jumpToTrace(item.trace_id)}>
                        {item.trace_id ? `${item.trace_id.slice(0, 12)}...` : '未记录'}
                      </button>
                    </td>
                    <td><code>{item.session_id || '未记录'}</code></td>
                    <td><code>{item.message_id || '未记录'}</code></td>
                    <td><span className="compression-stage-badge">{COMPRESSION_STAGE_LABEL[item.stage]}</span></td>
                    <td>{COMPRESSION_SCOPE_LABEL[item.scope]}</td>
                    <td>{COMPRESSION_TRIGGER_REASON_LABEL[item.trigger_reason]}</td>
                    <td>{item.raw_tokens}</td>
                    <td>{item.final_tokens}</td>
                    <td><span className={`compression-ratio ${ratioTone}`}>{formatRatio(item.total_compression_ratio)}</span></td>
                    <td>
                      <span className={`compression-status-badge status-${item.display_status.toLowerCase()}`}>
                        {COMPRESSION_STATUS_LABEL[item.display_status] || item.display_status}
                      </span>
                    </td>
                    <td>
                      <div className="compression-row-actions">
                        <button onClick={() => openReplay(item.trace_id)} disabled={!item.trace_id}>回放</button>
                        <button onClick={() => jumpToTrace(item.trace_id)} disabled={!item.trace_id}>Trace</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="audit-pagination compression-pagination">
        <button
          disabled={compressionAuditPage <= 1 || isLoadingCompressionAudits}
          onClick={() => setCompressionAuditPage(Math.max(1, compressionAuditPage - 1))}
        >
          上一页
        </button>
        <span>第 {compressionAuditPage} / {totalPages} 页（共 {compressionAuditTotal} 条）</span>
        <button
          disabled={compressionAuditPage >= totalPages || isLoadingCompressionAudits}
          onClick={() => setCompressionAuditPage(Math.min(totalPages, compressionAuditPage + 1))}
        >
          下一页
        </button>
      </div>

      <CompressionReplayDrawer />
    </div>
  );
};

export default CompressionAuditViewer;
