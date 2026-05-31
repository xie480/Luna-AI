import React, { useEffect, useRef, useState } from 'react';
import { useTelemetryStore, MetricsDataPoint } from '../../../stores/telemetryStore';
import { fetchMetrics } from '../../../services/telemetryService';

type MetricTab = 'cpu' | 'memory' | 'goroutines' | 'tokens' | 'tools';

/**
 * MetricsChart: 监控指标曲线图
 * 使用原生 Canvas 绘制 CPU/内存/协程数/Token 消耗趋势。
 * 数据来源：Go Runtime 内存中的 Ring Buffer（通过 HTTP API 拉取）。
 * 严格按照"一次完整的请求-响应全流程"作为一条独立记录进行聚合和展示。
 */
const MetricsChart: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { metrics, metricsRange, isLoadingMetrics, setMetrics, setMetricsRange, setLoadingMetrics } = useTelemetryStore();
  const [activeTab, setActiveTab] = useState<MetricTab>('cpu');

  // 切换时间范围时重新拉取，并设置定时轮询以支持实时更新
  useEffect(() => {
    let isMounted = true;
    const loadMetrics = async (showLoading = false) => {
      if (showLoading) setLoadingMetrics(true);
      try {
        const data = await fetchMetrics(metricsRange);
        if (isMounted) {
          setMetrics(data);
        }
      } catch (err) {
        console.error('获取监控指标失败:', err);
      } finally {
        if (isMounted && showLoading) {
          setLoadingMetrics(false);
        }
      }
    };

    // 初始加载
    loadMetrics(true);

    // 定时轮询 (每 3 秒)
    const intervalId = setInterval(() => {
      loadMetrics(false);
    }, 3000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [metricsRange, setMetrics, setLoadingMetrics]);

  // 绘制曲线
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || metrics.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);

    const padding = { top: 20, right: 20, bottom: 30, left: 50 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;

    const getMetricValue = (m: MetricsDataPoint): number => {
      switch (activeTab) {
        case 'cpu': return m.system_cpu_usage || 0;
        case 'memory': return m.system_memory_usage || 0;
        case 'goroutines': return m.go_goroutines_count || 0;
        case 'tokens': return m.llm_token_consumption || 0;
        case 'tools': return m.tool_call_failure_rate || 0;
        default: return 0;
      }
    };

    const values = metrics.map(getMetricValue);
    const maxVal = Math.max(...values, 10);
    const minVal = 0;

    ctx.strokeStyle = '#4fc3f7';
    ctx.lineWidth = 2;
    ctx.beginPath();

    metrics.forEach((point, index) => {
      const x = padding.left + (index / Math.max(1, metrics.length - 1)) * plotWidth;
      const val = getMetricValue(point);
      const y = padding.top + plotHeight - ((val - minVal) / (maxVal - minVal)) * plotHeight;

      index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });

    ctx.stroke();

    // 绘制坐标轴
    ctx.strokeStyle = '#2d2d44';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, height - padding.bottom);
    ctx.lineTo(width - padding.right, height - padding.bottom);
    ctx.stroke();

    // 绘制最大值和 0 值刻度
    ctx.fillStyle = '#888';
    ctx.font = '12px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(maxVal.toFixed(1), padding.left - 8, padding.top + 4);
    ctx.fillText('0', padding.left - 8, height - padding.bottom + 4);
  }, [metrics, activeTab]);

  return (
    <div className="metrics-chart">
      {/* 时间范围切换 */}
      <div className="metrics-range-selector">
        <button className={metricsRange === '1h' ? 'active' : ''} onClick={() => setMetricsRange('1h')}>
          最近 1 小时
        </button>
        <button className={metricsRange === '6h' ? 'active' : ''} onClick={() => setMetricsRange('6h')}>
          最近 6 小时
        </button>
        <button className={metricsRange === '24h' ? 'active' : ''} onClick={() => setMetricsRange('24h')}>
          最近 24 小时
        </button>
      </div>

      {/* 指标选择 */}
      <div className="metrics-tabs">
        <button className={activeTab === 'cpu' ? 'active' : ''} onClick={() => setActiveTab('cpu')}>CPU 使用率</button>
        <button className={activeTab === 'memory' ? 'active' : ''} onClick={() => setActiveTab('memory')}>内存 (MB)</button>
        <button className={activeTab === 'goroutines' ? 'active' : ''} onClick={() => setActiveTab('goroutines')}>协程数</button>
        <button className={activeTab === 'tokens' ? 'active' : ''} onClick={() => setActiveTab('tokens')}>Token 消耗</button>
        <button className={activeTab === 'tools' ? 'active' : ''} onClick={() => setActiveTab('tools')}>工具失败率</button>
      </div>

      {/* 曲线图区域 */}
      <canvas ref={canvasRef} width={600} height={300} style={{ width: '100%', height: 300 }} />

      {isLoadingMetrics && <div className="metrics-loading">加载中...</div>}

      {metrics.length === 0 && !isLoadingMetrics && (
        <div className="metrics-empty" style={{ position: 'absolute', top: '60%', left: '50%', transform: 'translate(-50%, -50%)', color: '#666' }}>
          暂无监控数据
        </div>
      )}
    </div>
  );
};

export default MetricsChart;
