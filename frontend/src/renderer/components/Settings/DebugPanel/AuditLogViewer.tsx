import React, { useEffect, useCallback } from 'react';
import { useTelemetryStore } from '../../../stores/telemetryStore';
import { fetchAuditLogs } from '../../../services/telemetryService';

/**
 * AuditLogViewer: 审计日志查看器
 * 支持按操作类型、状态、时间范围分页查询。
 * 注意：safeAuditLogs 兜底确保后端返回 null 时不会导致 .map() 崩溃
 */
const AuditLogViewer: React.FC = () => {
  const {
    auditLogs, auditLogTotal, auditLogPage, auditLogPageSize,
    auditLogFilters,
    setAuditLogs, setAuditLogFilter, setAuditLogPage, setLoadingAuditLogs,
  } = useTelemetryStore();

  // 确保 auditLogs 是数组（兜底策略，防止后端返回 null 导致 .map 崩溃）
  const safeAuditLogs = Array.isArray(auditLogs) ? auditLogs : [];

  const loadData = useCallback(async () => {
    setLoadingAuditLogs(true);
    try {
      const result = await fetchAuditLogs({
        page: auditLogPage,
        pageSize: auditLogPageSize,
        ...auditLogFilters,
      });
      setAuditLogs(result.data, result.total);
    } catch (err) {
      console.error('获取审计日志失败:', err);
    } finally {
      setLoadingAuditLogs(false);
    }
  }, [auditLogPage, auditLogPageSize, auditLogFilters, setAuditLogs, setLoadingAuditLogs]);

  // 首次加载或筛选条件变化时重载
  useEffect(() => {
    loadData();
  }, [loadData]);

  const totalPages = Math.max(1, Math.ceil(auditLogTotal / auditLogPageSize));

  return (
    <div className="audit-log-viewer">
      {/* 筛选栏 */}
      <div className="audit-filters">
        <select
          value={auditLogFilters.action_type || ''}
          onChange={(e) => setAuditLogFilter({ action_type: e.target.value || undefined })}
        >
          <option value="">所有操作类型</option>
          <option value="TOOL_CALL">工具调用</option>
          <option value="MEMORY_COMMIT">记忆提交</option>
          <option value="STATE_CHANGE">状态变更</option>
        </select>

        <select
          value={auditLogFilters.status || ''}
          onChange={(e) => setAuditLogFilter({ status: e.target.value || undefined })}
        >
          <option value="">所有状态</option>
          <option value="SUCCESS">成功</option>
          <option value="FAILED">失败</option>
          <option value="DENIED">已拒绝</option>
          <option value="TIMEOUT">超时</option>
        </select>
      </div>

      {/* 日志列表 */}
      <table className="audit-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>操作</th>
            <th>风险等级</th>
            <th>状态</th>
            <th>TraceID</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {safeAuditLogs.map((log) => (
            <tr key={log.id} className={`risk-${log.risk_level.toLowerCase()}`}>
              <td>{new Date(log.timestamp).toLocaleString()}</td>
              <td>
                <span className="operation-name">{log.operation}</span>
                <span className="action-type">{log.action_type}</span>
              </td>
              <td>
                <span className={`risk-badge ${log.risk_level.toLowerCase()}`}>
                  {log.risk_level}
                </span>
              </td>
              <td>
                <span className={`status-badge ${log.status.toLowerCase()}`}>
                  {log.status}
                </span>
              </td>
              <td>
                <button
                  className="trace-link"
                  onClick={() => {
                    useTelemetryStore.getState().setCurrentTraceId(log.trace_id);
                    useTelemetryStore.getState().setOpen(true); // 切换到链路标签
                  }}
                >
                  {log.trace_id.slice(0, 12)}...
                </button>
              </td>
              <td>
                {log.error_msg && <span className="error-msg">{log.error_msg}</span>}
                {log.requires_approval && (
                  <span className={`approval-badge ${log.user_approved ? 'approved' : 'denied'}`}>
                    {log.user_approved ? '已授权' : '未授权'}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* 分页 */}
      <div className="audit-pagination">
        <button
          disabled={auditLogPage <= 1}
          onClick={() => setAuditLogPage(Math.max(1, auditLogPage - 1))}
        >
          上一页
        </button>
        <span>第 {auditLogPage} / {totalPages} 页（共 {auditLogTotal} 条）</span>
        <button
          disabled={auditLogPage >= totalPages}
          onClick={() => setAuditLogPage(Math.min(totalPages, auditLogPage + 1))}
        >
          下一页
        </button>
      </div>
    </div>
  );
};

export default AuditLogViewer;
