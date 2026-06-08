import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  COMPRESSION_SCOPE_LABEL,
  COMPRESSION_STAGE_LABEL,
  COMPRESSION_STATUS_LABEL,
  COMPRESSION_TRIGGER_REASON_LABEL,
} from '../../../../shared/enum';
import { useSystemStore } from '../../../stores/systemStore';
import { useTelemetryStore } from '../../../stores/telemetryStore';
import type { CompressionReplayEvent } from '../../../types/compressionAudit';

/**
 * 将比例转换为百分比文本。
 *
 * 做什么：统一格式化压缩率字段。
 * 为什么这样做：后端返回 after/before 小数，UI 需要展示为用户可读百分比。
 * 输入输出：输入 0 到 1 附近的小数，输出百分比字符串。
 * 边界条件：非法数字统一显示为 0.0%。
 * 异常行为：本函数不抛异常。
 */
function formatRatio(ratio: number): string {
  if (!Number.isFinite(ratio)) return '0.0%';
  return `${(ratio * 100).toFixed(1)}%`;
}

/**
 * 将 ISO 时间转为本地时间文本。
 *
 * 做什么：统一处理回放抽屉中的时间展示。
 * 为什么这样做：后端使用 UTC ISO 或毫秒时间戳，前端诊断面板应按本地时间阅读。
 * 输入输出：输入 ISO 字符串，输出本地化字符串。
 * 边界条件：空值显示为“未记录”。
 * 异常行为：非法时间不抛异常，显示原始值。
 */
function formatTime(value: string): string {
  if (!value) return '未记录';
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return value;
  return time.toLocaleString();
}

/**
 * 复制文本到系统剪贴板。
 *
 * 做什么：封装 TraceID 和结构化摘要复制操作。
 * 为什么这样做：复制属于用户反馈链路，需要统一成功与失败提示。
 * 输入输出：输入待复制文本和成功提示，无返回值。
 * 边界条件：剪贴板权限不可用时提示失败，不影响抽屉展示。
 * 异常行为：捕获浏览器剪贴板异常并展示可解释提示。
 */
async function copyText(text: string, successMessage: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    useSystemStore.getState().showGlobalMessage(successMessage);
  } catch {
    useSystemStore.getState().showGlobalMessage('复制失败，请检查剪贴板权限');
  }
}

/**
 * 压缩指标摘要卡片。
 *
 * 做什么：展示原始、裁剪后、摘要后、最终 Token 与压缩率。
 * 为什么这样做：Token 变化是压缩审计的核心验收项，需要在总览和阶段详情中稳定复用。
 * 输入输出：输入标题、数值和可选强调等级，输出卡片 UI。
 * 边界条件：数值非法时显示 0。
 * 异常行为：无。
 */
const CompressionMetricSummaryCard: React.FC<{
  title: string;
  value: string | number;
  tone?: 'normal' | 'info' | 'warning' | 'danger';
}> = ({ title, value, tone = 'normal' }) => (
  <div className={`compression-metric-card ${tone}`}>
    <span className="compression-metric-title">{title}</span>
    <strong className="compression-metric-value">{value}</strong>
  </div>
);

/**
 * 压缩阶段详情指标卡片。
 *
 * 做什么：在阶段详情中展示单阶段 Token 演化。
 * 为什么这样做：详情抽屉必须回答“哪一步产生了主要 Token 收缩”。
 * 输入输出：输入当前事件，输出阶段指标网格。
 * 边界条件：缺失中间 Token 字段时显示 0。
 * 异常行为：无。
 */
const CompressionStageMetricCard: React.FC<{ event: CompressionReplayEvent }> = ({ event }) => (
  <div className="compression-stage-metrics">
    <CompressionMetricSummaryCard title="原始 Token" value={event.raw_tokens} />
    <CompressionMetricSummaryCard title="裁剪后 Token" value={event.after_trim_tokens} />
    <CompressionMetricSummaryCard title="摘要后 Token" value={event.after_summary_tokens} />
    <CompressionMetricSummaryCard title="最终 Token" value={event.final_tokens} tone="info" />
    <CompressionMetricSummaryCard title="阶段压缩率" value={formatRatio(event.stage_compression_ratio)} tone="warning" />
    <CompressionMetricSummaryCard title="总压缩率" value={formatRatio(event.total_compression_ratio)} tone="warning" />
  </div>
);

/**
 * 压缩回放详情抽屉。
 *
 * 做什么：展示单条压缩审计记录的总览、阶段时间线、阶段详情和 Trace 联动操作。
 * 为什么这样做：计划要求采用“列表 + 详情抽屉”，避免打断列表筛选上下文。
 * 输入输出：从 telemetryStore 读取 selectedCompressionReplay 与加载状态，无外部 props。
 * 边界条件：接口失败、空事件、字段缺失均显示明确空态或错误态。
 * 异常行为：用户操作失败时通过全局提示说明，不抛出未捕获异常。
 */
const CompressionReplayDrawer: React.FC = () => {
  const {
    selectedCompressionReplay,
    isCompressionReplayOpen,
    isLoadingCompressionReplay,
    compressionReplayError,
    setCompressionReplayOpen,
    setCurrentTraceId,
    setActiveDebugTab,
  } = useTelemetryStore();
  const [activeEventIndex, setActiveEventIndex] = useState(0);

  const events = selectedCompressionReplay?.events ?? [];
  const activeEvent = events[activeEventIndex] ?? null;

  useEffect(() => {
    setActiveEventIndex(0);
  }, [selectedCompressionReplay?.trace_id]);

  const summaryText = useMemo(() => {
    if (!selectedCompressionReplay) return '';
    const summary = selectedCompressionReplay.summary;
    return [
      `TraceID: ${selectedCompressionReplay.trace_id}`,
      `SessionID: ${selectedCompressionReplay.session_id || '未记录'}`,
      `MessageID: ${selectedCompressionReplay.message_id || '未记录'}`,
      `总原始 Token: ${summary.raw_tokens}`,
      `总最终 Token: ${summary.final_tokens}`,
      `总压缩率: ${formatRatio(summary.total_compression_ratio)}`,
      `最终策略: ${summary.final_strategy || '未记录'}`,
      `状态: ${COMPRESSION_STATUS_LABEL[summary.display_status] || summary.display_status}`,
      `失败原因: ${summary.failure_reason || '无'}`,
    ].join('\n');
  }, [selectedCompressionReplay]);

  const handleClose = useCallback(() => {
    setCompressionReplayOpen(false);
  }, [setCompressionReplayOpen]);

  const handleTraceJump = useCallback(() => {
    if (!selectedCompressionReplay?.trace_id) return;
    setCurrentTraceId(selectedCompressionReplay.trace_id);
    setActiveDebugTab('traces');
    setCompressionReplayOpen(false);
  }, [selectedCompressionReplay?.trace_id, setActiveDebugTab, setCompressionReplayOpen, setCurrentTraceId]);

  if (!isCompressionReplayOpen) return null;

  return (
    <div className="compression-drawer-mask" onMouseDown={(event) => event.stopPropagation()}>
      <aside className="compression-replay-drawer" role="dialog" aria-label="压缩回放详情">
        <div className="compression-drawer-header">
          <div>
            <h3>压缩回放详情</h3>
            <p>仅展示后端已脱敏的预览与结构化审计指标</p>
          </div>
          <button className="compression-drawer-close" onClick={handleClose}>✕</button>
        </div>

        {isLoadingCompressionReplay ? (
          <div className="compression-drawer-state">
            <div className="compression-skeleton large" />
            <div className="compression-skeleton" />
            <div className="compression-skeleton" />
          </div>
        ) : compressionReplayError ? (
          <div className="compression-drawer-state error">
            <h4>压缩回放加载失败</h4>
            <p>{compressionReplayError}</p>
            <button onClick={handleClose}>关闭</button>
          </div>
        ) : !selectedCompressionReplay || events.length === 0 ? (
          <div className="compression-drawer-state empty">当前链路未生成可回放快照</div>
        ) : (
          <div className="compression-drawer-body">
            <section className="compression-overview-section">
              <div className="compression-section-title">总览摘要</div>
              <div className="compression-overview-grid">
                <CompressionMetricSummaryCard title="总原始 Token" value={selectedCompressionReplay.summary.raw_tokens} />
                <CompressionMetricSummaryCard title="总最终 Token" value={selectedCompressionReplay.summary.final_tokens} tone="info" />
                <CompressionMetricSummaryCard title="总压缩率" value={formatRatio(selectedCompressionReplay.summary.total_compression_ratio)} tone="warning" />
                <CompressionMetricSummaryCard
                  title="状态"
                  value={COMPRESSION_STATUS_LABEL[selectedCompressionReplay.summary.display_status] || selectedCompressionReplay.summary.display_status}
                  tone={selectedCompressionReplay.summary.display_status === 'HARD_TRUNCATED' ? 'danger' : 'normal'}
                />
              </div>
              <div className="compression-summary-fields">
                <span>TraceID：<code>{selectedCompressionReplay.trace_id}</code></span>
                <span>SessionID：<code>{selectedCompressionReplay.session_id || '未记录'}</code></span>
                <span>MessageID：<code>{selectedCompressionReplay.message_id || '未记录'}</code></span>
                <span>最终策略：{COMPRESSION_STAGE_LABEL[selectedCompressionReplay.summary.final_strategy as keyof typeof COMPRESSION_STAGE_LABEL] || selectedCompressionReplay.summary.final_strategy || '未记录'}</span>
                <span>触发时间：{formatTime(selectedCompressionReplay.summary.started_at)}</span>
                <span>失败原因：{selectedCompressionReplay.summary.failure_reason || '无'}</span>
              </div>
            </section>

            <section className="compression-timeline-section">
              <div className="compression-section-title">阶段时间线</div>
              <div className="compression-timeline">
                {events.map((event, index) => (
                  <button
                    key={`${event.stage}-${event.timestamp_ms}-${index}`}
                    className={`compression-timeline-item ${index === activeEventIndex ? 'active' : ''} status-${event.display_status.toLowerCase()}`}
                    onClick={() => setActiveEventIndex(index)}
                  >
                    <span className="compression-timeline-dot" />
                    <span className="compression-timeline-main">
                      <strong>{COMPRESSION_STAGE_LABEL[event.stage]}</strong>
                      <small>{COMPRESSION_SCOPE_LABEL[event.scope]} · {COMPRESSION_STATUS_LABEL[event.display_status] || event.display_status}</small>
                    </span>
                    <span className="compression-timeline-metrics">
                      {event.raw_tokens} → {event.final_tokens} · {formatRatio(event.stage_compression_ratio)}
                    </span>
                  </button>
                ))}
              </div>
            </section>

            {activeEvent && (
              <section className="compression-stage-detail-section">
                <div className="compression-section-title">阶段详情</div>
                <div className="compression-stage-detail-card">
                  <div className="compression-stage-detail-header">
                    <div>
                      <h4>{COMPRESSION_STAGE_LABEL[activeEvent.stage]}</h4>
                      <p>{COMPRESSION_TRIGGER_REASON_LABEL[activeEvent.trigger_reason]}</p>
                    </div>
                    <span className={`compression-status-badge status-${activeEvent.display_status.toLowerCase()}`}>
                      {COMPRESSION_STATUS_LABEL[activeEvent.display_status] || activeEvent.display_status}
                    </span>
                  </div>

                  <CompressionStageMetricCard event={activeEvent} />

                  <div className="compression-detail-fields">
                    <span>作用域：{COMPRESSION_SCOPE_LABEL[activeEvent.scope]}</span>
                    <span>模型提供方：{activeEvent.model_provider || '未记录'}</span>
                    <span>模型地址摘要：{activeEvent.model_base_url || '未记录'}</span>
                    <span>模型 ID：{activeEvent.model_id || '未记录'}</span>
                    <span>来源键名：{activeEvent.source_keys.length > 0 ? activeEvent.source_keys.join('、') : '未记录'}</span>
                    <span>失败原因：{activeEvent.failure_reason || '无'}</span>
                  </div>

                  <div className="compression-preview-grid">
                    <div>
                      <div className="compression-preview-title">处理前脱敏预览</div>
                      <pre>{activeEvent.preview_before || '无预览内容'}</pre>
                    </div>
                    <div>
                      <div className="compression-preview-title">处理后脱敏预览</div>
                      <pre>{activeEvent.preview_after || '无预览内容'}</pre>
                    </div>
                  </div>
                </div>
              </section>
            )}

            <section className="compression-actions-section">
              <button onClick={handleTraceJump}>查看链路追踪</button>
              <button onClick={() => copyText(selectedCompressionReplay.trace_id, 'TraceID 已复制')}>复制 TraceID</button>
              <button onClick={() => copyText(summaryText, '压缩摘要已复制')}>复制压缩摘要</button>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
};

export default CompressionReplayDrawer;
