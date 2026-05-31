import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { useTelemetryStore, TelemetrySpan } from '../../../stores/telemetryStore';
import { fetchTraces } from '../../../services/telemetryService';

/**
 * TraceViewer: 链路追踪查看器
 * 支持按 TraceID 查询完整调用链，以树形结构展示 Span 的父子关系。
 * 提供"最近 TraceID"列表，用户无需手动输入即可查询。
 */
const TraceViewer: React.FC = () => {
  const [inputTraceId, setInputTraceId] = useState('');
  const {
    traceSpans,
    traceTotal,
    tracePage,
    tracePageSize,
    isLoadingTrace,
    currentTraceId,
    setCurrentTraceId,
    setTraceSpans,
    setTracePage,
    setLoadingTrace,
  } = useTelemetryStore();

  const loadTraces = useCallback(async () => {
    setLoadingTrace(true);
    try {
      const { data, total } = await fetchTraces({
        page: tracePage,
        pageSize: tracePageSize,
        trace_id: currentTraceId || undefined,
      });
      setTraceSpans(data, total);
    } catch (err) {
      console.error('获取链路追踪失败:', err);
    } finally {
      setLoadingTrace(false);
    }
  }, [tracePage, tracePageSize, currentTraceId, setLoadingTrace, setTraceSpans]);

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  const handleSearch = useCallback(() => {
    setCurrentTraceId(inputTraceId.trim() || null);
  }, [inputTraceId, setCurrentTraceId]);

  const handleClearSearch = useCallback(() => {
    setInputTraceId('');
    setCurrentTraceId(null);
  }, [setCurrentTraceId]);

  /**
   * 计算 Span 的总耗时，用于进度条展示
   */
  const maxDuration = Math.max(...traceSpans.map((s) => s.duration_ms), 1);

  /**
   * 根据 parent_span_id 构建树形层级
   */
  const spanMap = new Map<string, TelemetrySpan>();
  traceSpans.forEach((s) => spanMap.set(s.span_id, s));

  // 根节点：没有父节点或父节点不在当前列表中
  const rootSpans = traceSpans.filter(
    (s) => !s.parent_span_id || !spanMap.has(s.parent_span_id)
  );

  // 为不同的 trace_id 生成不同的背景色
  const traceColors = useMemo(() => {
    const colors = [
      'rgba(79, 195, 247, 0.05)',
      'rgba(46, 204, 113, 0.05)',
      'rgba(155, 89, 182, 0.05)',
      'rgba(241, 196, 15, 0.05)',
      'rgba(230, 126, 34, 0.05)',
    ];
    const map = new Map<string, string>();
    let colorIndex = 0;
    traceSpans.forEach((span) => {
      if (!map.has(span.trace_id)) {
        map.set(span.trace_id, colors[colorIndex % colors.length]);
        colorIndex++;
      }
    });
    return map;
  }, [traceSpans]);

  return (
    <div className="trace-viewer">
      {/* 搜索栏 */}
      <div className="trace-search">
        <input
          type="text"
          placeholder="输入 TraceID 查询链路..."
          value={inputTraceId}
          onChange={(e) => setInputTraceId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button onClick={handleSearch} disabled={isLoadingTrace}>
          查询
        </button>
        {currentTraceId && (
          <button onClick={handleClearSearch} disabled={isLoadingTrace} style={{ backgroundColor: '#e74c3c' }}>
            清除
          </button>
        )}
      </div>

      {/* Span 树形列表 */}
      <div className="trace-spans">
        {isLoadingTrace && traceSpans.length === 0 ? (
          <div className="trace-empty">加载中...</div>
        ) : traceSpans.length === 0 ? (
          <div className="trace-empty">暂无链路追踪数据。</div>
        ) : (
          rootSpans.map((span) => (
            <SpanNode
              key={span.span_id}
              span={span}
              allSpans={traceSpans}
              spanMap={spanMap}
              maxDuration={maxDuration}
              depth={0}
              bgColor={traceColors.get(span.trace_id)}
            />
          ))
        )}
      </div>

      {/* 分页 */}
      {traceTotal > 0 && (
        <div className="audit-pagination">
          <span>
            共 {traceTotal} 条记录，第 {tracePage} 页
          </span>
          <div>
            <button
              disabled={tracePage <= 1 || isLoadingTrace}
              onClick={() => setTracePage(tracePage - 1)}
            >
              上一页
            </button>
            <button
              disabled={tracePage * tracePageSize >= traceTotal || isLoadingTrace}
              onClick={() => setTracePage(tracePage + 1)}
              style={{ marginLeft: 8 }}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * SpanNode: 递归渲染单个 Span 节点及其子 Span
 */
const SpanNode: React.FC<{
  span: TelemetrySpan;
  allSpans: TelemetrySpan[];
  spanMap: Map<string, TelemetrySpan>;
  maxDuration: number;
  depth: number;
  bgColor?: string;
}> = ({ span, allSpans, spanMap, maxDuration, depth, bgColor }) => {
  // 查找子节点
  const children = allSpans.filter((s) => s.parent_span_id === span.span_id);

  return (
    <div className="span-node" style={{ marginLeft: depth * 24 }}>
      <div
        className={`span-row ${span.status === 'ERROR' ? 'span-error' : ''}`}
        style={{ backgroundColor: bgColor }}
      >
        {/* Span 名称 */}
        <span className="span-name">{span.name}</span>

        {/* 耗时进度条 */}
        <div className="span-duration-bar-bg">
          <div
            className="span-duration-bar"
            style={{ width: `${(span.duration_ms / maxDuration) * 100}%` }}
          />
        </div>

        {/* 耗时数值 */}
        <span className="span-duration">
          {span.duration_ms > 1000
            ? `${(span.duration_ms / 1000).toFixed(2)}s`
            : `${span.duration_ms}ms`}
        </span>

        {/* 状态标记 */}
        <span className={`span-status ${span.status.toLowerCase()}`}>
          {span.status}
        </span>

        {/* 服务标识 */}
        <span className="span-service">{span.service}</span>
      </div>

      {/* 递归渲染子节点 */}
      {children.map((child) => (
        <SpanNode
          key={child.span_id}
          span={child}
          allSpans={allSpans}
          spanMap={spanMap}
          maxDuration={maxDuration}
          depth={depth + 1}
          bgColor={bgColor}
        />
      ))}
    </div>
  );
};

export default TraceViewer;
