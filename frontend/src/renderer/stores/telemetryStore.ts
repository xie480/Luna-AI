import { create } from 'zustand';
import type {
  CompressionAuditFilters,
  CompressionAuditListItem,
  CompressionReplayDetail,
} from '../types/compressionAudit';

/**
 * 链路 Span 数据结构（与后端 trace_spans 表对齐）
 */
export interface TelemetrySpan {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;             // Span 名称，如 'LLM_Reasoning'
  service: string;          // 'electron', 'go_runtime', 'python_ai'
  start_time: string;
  end_time: string | null;
  duration_ms: number;
  status: 'OK' | 'ERROR';
  attributes: Record<string, unknown>;  // 扩展属性，如 tokens_used
}

/**
 * 审计日志数据结构（与后端 audit_logs 表对齐）
 */
export interface AuditLogEntry {
  id: string;
  trace_id: string;
  timestamp: string;
  plan_id: string;
  node_id: string;
  action_type: string;      // 'TOOL_CALL', 'MEMORY_COMMIT', 'STATE_CHANGE'
  resource: string;
  operation: string;
  payload: Record<string, unknown>;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  status: string;           // 'SUCCESS', 'FAILED', 'DENIED', 'TIMEOUT'
  error_msg: string;
  requires_approval: boolean;
  user_approved: boolean | null;
}

/**
 * 监控指标数据点（Ring Buffer 中的一个数据点）
 * 与 Go 后端 telemetry.MetricPoint 结构对齐
 */
export interface MetricsDataPoint {
  timestamp: string | number;
  system_cpu_usage: number;
  system_memory_usage: number;
  go_goroutines_count: number;
  llm_token_consumption: number;
  tool_call_failure_rate: number;
}

/** 诊断面板标签类型。 */
export type TelemetryDebugTab = 'metrics' | 'errors' | 'compressionAudit' | 'traces';

/**
 * 可观测性/诊断面板状态
 */
interface TelemetryState {
  // 面板可见性
  isOpen: boolean;
  activeDebugTab: TelemetryDebugTab;

  // 链路查询
  currentTraceId: string | null;
  traceSpans: TelemetrySpan[];
  traceTotal: number;
  tracePage: number;
  tracePageSize: number;
  isLoadingTrace: boolean;

  // 审计日志查询
  auditLogs: AuditLogEntry[];
  auditLogTotal: number;
  auditLogPage: number;
  auditLogPageSize: number;
  auditLogFilters: {
    action_type?: string;
    status?: string;
    start_time?: string;
    end_time?: string;
  };
  isLoadingAuditLogs: boolean;

  // 压缩审计查询
  compressionAudits: CompressionAuditListItem[];
  compressionAuditTotal: number;
  compressionAuditPage: number;
  compressionAuditPageSize: number;
  compressionAuditFilters: CompressionAuditFilters;
  isLoadingCompressionAudits: boolean;
  compressionAuditError: string;
  selectedCompressionReplay: CompressionReplayDetail | null;
  isCompressionReplayOpen: boolean;
  isLoadingCompressionReplay: boolean;
  compressionReplayError: string;

  // 监控指标（Ring Buffer 镜像，最多保存 60 个数据点用于前端绘图）
  metrics: MetricsDataPoint[];
  metricsRange: '1h' | '6h' | '24h';
  isLoadingMetrics: boolean;

  // Actions
  setOpen: (isOpen: boolean) => void;
  setActiveDebugTab: (tab: TelemetryDebugTab) => void;

  // 链路
  setCurrentTraceId: (traceId: string | null) => void;
  setTraceSpans: (spans: TelemetrySpan[], total: number) => void;
  setTracePage: (page: number) => void;
  setLoadingTrace: (loading: boolean) => void;

  // 审计日志
  setAuditLogs: (logs: AuditLogEntry[], total: number) => void;
  setAuditLogFilter: (filters: Partial<TelemetryState['auditLogFilters']>) => void;
  setAuditLogPage: (page: number) => void;
  setLoadingAuditLogs: (loading: boolean) => void;

  // 压缩审计
  setCompressionAudits: (items: CompressionAuditListItem[], total: number) => void;
  setCompressionAuditFilters: (filters: Partial<CompressionAuditFilters>) => void;
  resetCompressionAuditFilters: () => void;
  setCompressionAuditPage: (page: number) => void;
  setLoadingCompressionAudits: (loading: boolean) => void;
  setCompressionAuditError: (error: string) => void;
  setSelectedCompressionReplay: (detail: CompressionReplayDetail | null) => void;
  setCompressionReplayOpen: (isOpen: boolean) => void;
  setLoadingCompressionReplay: (loading: boolean) => void;
  setCompressionReplayError: (error: string) => void;

  // 监控指标
  setMetrics: (points: MetricsDataPoint[]) => void;
  setMetricsRange: (range: '1h' | '6h' | '24h') => void;
  setLoadingMetrics: (loading: boolean) => void;
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  isOpen: false,
  activeDebugTab: 'errors',

  currentTraceId: null,
  traceSpans: [],
  traceTotal: 0,
  tracePage: 1,
  tracePageSize: 50,
  isLoadingTrace: false,

  auditLogs: [],
  auditLogTotal: 0,
  auditLogPage: 1,
  auditLogPageSize: 50,
  auditLogFilters: {},
  isLoadingAuditLogs: false,

  compressionAudits: [],
  compressionAuditTotal: 0,
  compressionAuditPage: 1,
  compressionAuditPageSize: 20,
  compressionAuditFilters: {},
  isLoadingCompressionAudits: false,
  compressionAuditError: '',
  selectedCompressionReplay: null,
  isCompressionReplayOpen: false,
  isLoadingCompressionReplay: false,
  compressionReplayError: '',

  metrics: [],
  metricsRange: '1h',
  isLoadingMetrics: false,

  setOpen: (isOpen) => set({ isOpen }),
  setActiveDebugTab: (activeDebugTab) => set({ activeDebugTab }),

  setCurrentTraceId: (currentTraceId) => set({ currentTraceId, tracePage: 1 }),
  setTraceSpans: (traceSpans, total) => set({ traceSpans, traceTotal: total }),
  setTracePage: (page) => set({ tracePage: page }),
  setLoadingTrace: (isLoadingTrace) => set({ isLoadingTrace }),

  setAuditLogs: (logs, total) => set({ auditLogs: logs, auditLogTotal: total }),
  setAuditLogFilter: (filters) =>
    set((state) => ({ auditLogFilters: { ...state.auditLogFilters, ...filters }, auditLogPage: 1 })),
  setAuditLogPage: (page) => set({ auditLogPage: page }),
  setLoadingAuditLogs: (isLoadingAuditLogs) => set({ isLoadingAuditLogs }),

  setCompressionAudits: (compressionAudits, total) =>
    set({ compressionAudits, compressionAuditTotal: total }),
  setCompressionAuditFilters: (filters) =>
    set((state) => ({
      compressionAuditFilters: { ...state.compressionAuditFilters, ...filters },
      compressionAuditPage: 1,
    })),
  resetCompressionAuditFilters: () => set({ compressionAuditFilters: {}, compressionAuditPage: 1 }),
  setCompressionAuditPage: (page) => set({ compressionAuditPage: page }),
  setLoadingCompressionAudits: (isLoadingCompressionAudits) => set({ isLoadingCompressionAudits }),
  setCompressionAuditError: (compressionAuditError) => set({ compressionAuditError }),
  setSelectedCompressionReplay: (selectedCompressionReplay) => set({ selectedCompressionReplay }),
  setCompressionReplayOpen: (isCompressionReplayOpen) => set({ isCompressionReplayOpen }),
  setLoadingCompressionReplay: (isLoadingCompressionReplay) => set({ isLoadingCompressionReplay }),
  setCompressionReplayError: (compressionReplayError) => set({ compressionReplayError }),

  setMetrics: (metrics) => set({ metrics }),
  setMetricsRange: (metricsRange) => set({ metricsRange }),
  setLoadingMetrics: (isLoadingMetrics) => set({ isLoadingMetrics }),
}));
