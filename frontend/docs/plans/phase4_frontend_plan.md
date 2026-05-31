# Phase 4: 前端可观测性架构与监控诊断面板实施方案

## 1. 文档概览

### 1.1 本文目标
本文旨在为 Luna 桌面 AI 助理设计一套**前端可观测性架构与监控诊断面板**的完整实施方案。在 Phase 4 后端可观测性体系（日志、链路追踪、审计）的基础上，明确前端如何承接 TraceID 链路追踪埋点、异常捕获与上报、诊断面板渲染以及可观测性相关代码的组织规范。

### 1.2 适用范围
本方案适用于 Electron Renderer 进程（React + TypeScript）中所有与可观测性相关的模块，包括：
- WebSocket 通信层的 TraceID 埋点机制
- 前端异常捕获与日志上报通道
- 监控诊断面板（Debug Dashboard）的 UI 组件与状态管理
- 与后端 Telemetry API 的数据拉取协议

## 2. 前端技术栈选型（可观测性专项）

| 技术/库 | 用途 | 选型理由 |
|:---|:---|:---|
| Zustand 4.x | 诊断面板全局状态管理 | 支持高频局部更新，避免顶层重渲染 |
| native `CustomEvent` | 跨组件异常/日志事件桥接 | 零依赖，与现有 Live2D 情绪事件机制保持一致 |
| React Error Boundary | 组件级异常捕获 | React 官方推荐的异常隔离方案 |
| `window.onerror` / `onunhandledrejection` | 全局未捕获异常监听 | 捕获 React 边界之外的 JS 运行时错误 |
| ECharts 或 Recharts | 监控指标曲线图（CPU、Token 消耗） | 本地轻量级图表库 |
| `fetch` (AbortController) | 调用后端 Telemetry HTTP API | 无需额外 HTTP 客户端依赖 |

## 3. 核心目录结构设计

新增和修改的文件如下（仅列举与可观测性相关的部分）：

```
frontend/src/
├── shared/
│   ├── enum.ts                          # [修改] 增加 Telemetry 相关消息类型与事件名
│   └── types.ts                         # [修改] 增加 Telemetry/诊断面板相关类型定义
│
└── renderer/
    ├── components/
    │   ├── Settings/
    │   │   ├── DebugPanel/               # [新增] 监控诊断面板
    │   │   │   ├── TraceViewer.tsx        # 链路详情查看器（按 TraceID 查询 Spans）
    │   │   │   ├── AuditLogViewer.tsx     # 审计日志查看器（分页/筛选）
    │   │   │   ├── MetricsChart.tsx       # 监控指标曲线图（CPU/Token/协程数）
    │   │   │   └── index.tsx              # 诊断面板入口，整合上述子组件
    │   │   └── ...
    │   └── ErrorBoundary/
    │       └── ErrorBoundary.tsx          # [新增] 全局 React 错误边界
    │
    ├── hooks/
    │   ├── useTelemetryAPI.ts             # [新增] Telemetry HTTP API 封装
    │   └── useTraceContext.ts              # [新增] 自动注入 TraceID 到 WebSocket 消息
    │
    ├── services/
    │   ├── wsManager.ts                  # [修改] 增强 TraceID 生成与注入
    │   ├── healthService.ts              # [未改动]
    │   └── telemetryService.ts            # [新增] 诊断数据拉取服务
    │
    ├── stores/
    │   ├── telemetryStore.ts              # [新增] 可观测性/诊断面板状态切片
    │   └── systemStore.ts                # [修改] 增加异常日志缓冲、诊断面板开关
    │
    └── utils/
        └── telemetry.ts                   # [新增] TraceID 生成、异常格式化工具函数
```

## 4. 状态管理方案

### 4.1 可观测性状态切片（`telemetryStore.ts`）

诊断面板的数据通过 HTTP API 从 Go Runtime 拉取，不由 WebSocket 实时推送，因此状态设计为**按需加载 + 本地缓存**模式。

```typescript
// frontend/src/renderer/stores/telemetryStore.ts

import { create } from 'zustand';

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
 */
export interface MetricsDataPoint {
  timestamp: number;
  cpu_percent: number;
  memory_mb: number;
  goroutines: number;
  token_consumption: Record<string, number>; // 按模型 Provider 分类
  tool_failure_rate: number;
}

/**
 * 可观测性/诊断面板状态
 */
interface TelemetryState {
  // 面板可见性
  isOpen: boolean;

  // 链路查询
  currentTraceId: string | null;
  traceSpans: TelemetrySpan[];
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

  // 监控指标（Ring Buffer 镜像，最多保存 60 个数据点用于前端绘图）
  metrics: MetricsDataPoint[];
  metricsRange: '1h' | '6h' | '24h';
  isLoadingMetrics: boolean;

  // Actions
  setOpen: (isOpen: boolean) => void;

  // 链路
  setCurrentTraceId: (traceId: string | null) => void;
  setTraceSpans: (spans: TelemetrySpan[]) => void;
  setLoadingTrace: (loading: boolean) => void;

  // 审计日志
  setAuditLogs: (logs: AuditLogEntry[], total: number) => void;
  setAuditLogFilter: (filters: Partial<TelemetryState['auditLogFilters']>) => void;
  setAuditLogPage: (page: number) => void;
  setLoadingAuditLogs: (loading: boolean) => void;

  // 监控指标
  setMetrics: (points: MetricsDataPoint[]) => void;
  setMetricsRange: (range: '1h' | '6h' | '24h') => void;
  setLoadingMetrics: (loading: boolean) => void;
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  isOpen: false,

  currentTraceId: null,
  traceSpans: [],
  isLoadingTrace: false,

  auditLogs: [],
  auditLogTotal: 0,
  auditLogPage: 1,
  auditLogPageSize: 50,
  auditLogFilters: {},
  isLoadingAuditLogs: false,

  metrics: [],
  metricsRange: '1h',
  isLoadingMetrics: false,

  setOpen: (isOpen) => set({ isOpen }),

  setCurrentTraceId: (currentTraceId) => set({ currentTraceId }),
  setTraceSpans: (traceSpans) => set({ traceSpans }),
  setLoadingTrace: (isLoadingTrace) => set({ isLoadingTrace }),

  setAuditLogs: (logs, total) => set({ auditLogs: logs, auditLogTotal: total }),
  setAuditLogFilter: (filters) =>
    set((state) => ({ auditLogFilters: { ...state.auditLogFilters, ...filters }, auditLogPage: 1 })),
  setAuditLogPage: (page) => set({ auditLogPage: page }),
  setLoadingAuditLogs: (isLoadingAuditLogs) => set({ isLoadingAuditLogs }),

  setMetrics: (metrics) => set({ metrics }),
  setMetricsRange: (metricsRange) => set({ metricsRange }),
  setLoadingMetrics: (isLoadingMetrics) => set({ isLoadingMetrics }),
}));
```

### 4.2 系统状态增强（修改 `systemStore.ts`）

在现有的 `SystemState` 中增加异常缓冲区和诊断面板开关：

```typescript
// 在 systemStore.ts 的 Interface SystemState 中新增：

interface SystemState {
  // ... 现有属性 ...

  // === 可观测性相关增强 ===

  // 前端异常缓冲区（环形缓冲，最多保留 100 条）
  frontendErrors: FrontendErrorEntry[];

  // 诊断面板是否打开（与 ModalPanelType 中的 'debug' 联动）
  isDiagnosticOpen: boolean;

  // 当前 TraceID（由 wsManager 自动维护，用于异常上报关联）
  currentTraceID: string | null;

  // Actions
  addFrontendError: (entry: FrontendErrorEntry) => void;
  clearFrontendErrors: () => void;
  setDiagnosticOpen: (isOpen: boolean) => void;
  setCurrentTraceID: (traceId: string | null) => void;
}

/**
 * 前端异常条目
 */
export interface FrontendErrorEntry {
  id: string;            // Snowflake ID
  timestamp: number;
  level: 'ERROR' | 'WARN' | 'CRITICAL';
  source: string;        // 异常来源，如 'react_renderer', 'websocket', 'live2d'
  message: string;
  stack?: string;
  trace_id?: string;     // 关联的 TraceID
  component_stack?: string; // React 组件栈（Error Boundary 捕获）
}
```

## 5. WebSocket 通信封装及 TraceID 链路追踪埋点

### 5.1 TraceID 生成与注入机制

前端目前已经通过 `generateId()`（Snowflake）生成 `trace_id`，但仅在 `send()` 方法中注入。Phase 4 需要将其提升为**全局自动埋点**：

```typescript
// frontend/src/renderer/hooks/useTraceContext.ts

import { useEffect, useRef } from 'react';
import { generateId } from '../../shared/utils/snowflake';
import { useSystemStore } from '../stores/systemStore';

/**
 * useTraceContext: 自动管理 TraceID 生命周期
 * 做什么：在组件的生命周期内维护一个全局 TraceID，并在组件卸载时自动清理。
 * 用于用户操作（如发送消息）时自动关联 TraceID，确保同一次交互的所有日志可追溯。
 */
export function useTraceContext() {
  const traceIdRef = useRef<string>(generateId());
  const { setCurrentTraceID, addSystemLog } = useSystemStore.getState();

  useEffect(() => {
    // 挂载时设置全局 TraceID
    const traceId = traceIdRef.current;
    setCurrentTraceID(traceId);
    addSystemLog(`[Trace] 初始化 TraceID: ${traceId}`);

    return () => {
      // 组件卸载时清除 TraceID（但保留日志，方便调试）
      addSystemLog(`[Trace] 清理 TraceID: ${traceId}`);
    };
  }, []);
}
```

### 5.2 WebSocket 管理器增强（修改 `wsManager.ts`）

在现有的 `WSManager` 中，`send()` 方法已经携带 `trace_id` 参数，但需要进一步强化：

1.  **接收消息时自动提取 `trace_id`**：当 Go 推送的消息中携带了后端生成的 `trace_id`，前端应当将其同步到 `systemStore`，确保后续错误日志正确关联。
2.  **新增 `EVT_TRACE_SPAN`、`EVT_AUDIT_LOG` 等 Go 端推送的可观测性事件**：在 `handleMessage()` 中增加对应 case，供诊断面板实时消费。

```typescript
// 修改位置：wsManager.ts 中的 onmessage 处理器

// === 在 WS_MSG_TYPE 常量中新增（enum.ts） ===
// EVT_TELEMETRY_TRACE: "EVT_TELEMETRY_TRACE",   // Go 推送的链路 Span
// EVT_TELEMETRY_METRICS: "EVT_TELEMETRY_METRICS", // Go 推送的监控指标

// === 在 handleMessage 方法中新增 case ===

// 在 handleMessage 函数开头，无论什么消息类型，都尝试更新 TraceID
private handleMessage(msg: WSMessage): void {
  const systemStore = useSystemStore.getState();

  // 关键增强：如果 Go 端返回的消息携带了 trace_id，同步到 systemStore
  // 确保后端的 TraceID 覆盖前端的初版（后端是权威）
  if (msg.trace_id && msg.trace_id !== systemStore.currentTraceID) {
    systemStore.setCurrentTraceID(msg.trace_id);
  }

  // ... 原有的 switch-case 逻辑保持不变 ...

  // 新增：Go 推送的链路 Span（仅在诊断面板开启时推送）
  case WS_MSG_TYPE.EVT_TELEMETRY_TRACE:
    const spanPayload = msg.payload as TelemetrySpan;
    useTelemetryStore.getState().setTraceSpans(
      [...useTelemetryStore.getState().traceSpans, spanPayload]
    );
    break;

  // 新增：Go 推送的实时监控指标（每秒推送一次）
  case WS_MSG_TYPE.EVT_TELEMETRY_METRICS:
    const metricsPayload = msg.payload as MetricsDataPoint;
    const telemetryStore = useTelemetryStore.getState();
    const updatedMetrics = [...telemetryStore.metrics, metricsPayload].slice(-60);
    telemetryStore.setMetrics(updatedMetrics);
    break;
}
```

### 5.3 发送消息的 TraceID 增强

```typescript
// 修改 wsManager.ts 中的 send 方法
public send(data: { type: string; payload: unknown }): void {
  if (this.ws && this.ws.readyState === WebSocket.OPEN) {
    // 优先使用 systemStore 中维护的全局 TraceID（由 useTraceContext 设置）
    // 如果不存在则新生成一个
    const currentTraceID = useSystemStore.getState().currentTraceID;
    const traceID = currentTraceID || `tr-${generateId()}`;

    const message = JSON.stringify({
      ...data,
      timestamp: Date.now(),
      trace_id: traceID,
    });
    this.ws.send(message);
    useSystemStore.getState().addSystemLog(`发送消息: ${data.type}, trace_id=${traceID}`);
  } else {
    useSystemStore.getState().addSystemLog('WebSocket 未连接，无法发送消息');
  }
}
```

## 6. UI 层异常捕获与日志上报

### 6.1 React Error Boundary

```typescript
// frontend/src/renderer/components/ErrorBoundary/ErrorBoundary.tsx

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { generateId } from '../../../shared/utils/snowflake';
import { useSystemStore } from '../../stores/systemStore';
import { FrontendErrorEntry } from '../../stores/systemStore';

interface Props {
  children: ReactNode;
  /** 错误来源标识，如 'chat_view', 'live2d_view', 'settings_panel' */
  source: string;
  /** 降级渲染的备用 UI */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * ErrorBoundary: React 错误边界组件
 * 做什么：捕获子组件渲染过程中的异常，防止整个应用白屏。
 * 同时将异常结构化为 FrontendErrorEntry 写入 systemStore，供诊断面板查阅。
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // 将异常结构化为 FrontendErrorEntry
    const entry: FrontendErrorEntry = {
      id: generateId(),
      timestamp: Date.now(),
      level: 'ERROR',
      source: this.props.source,
      message: error.message || '未知 React 渲染异常',
      stack: error.stack,
      trace_id: useSystemStore.getState().currentTraceID || undefined,
      component_stack: errorInfo.componentStack || undefined,
    };

    // 写入 systemStore（环形缓冲，最多 100 条）
    useSystemStore.getState().addFrontendError(entry);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      // 使用自定义 fallback 或默认降级 UI
      return (
        this.props.fallback || (
          <div style={{ padding: 24, color: '#e74c3c', textAlign: 'center' }}>
            <p>组件 <strong>{this.props.source}</strong> 发生异常，系统已记录此错误。</p>
            <button onClick={() => this.setState({ hasError: false, error: null })}>
              重试
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
```

### 6.2 全局 JS 异常监听

```typescript
// frontend/src/renderer/index.tsx （在应用入口初始化时挂载）

import { generateId } from '../shared/utils/snowflake';

/**
 * 初始化全局异常监听
 * 捕获 React ErrorBoundary 无法捕获的异常（如 setTimeout、Promise rejection）
 */
function initGlobalErrorListeners(): void {
  // 捕获未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    const systemStore = useSystemStore.getState();
    systemStore.addFrontendError({
      id: generateId(),
      timestamp: Date.now(),
      level: 'ERROR',
      source: 'global_promise',
      message: event.reason?.message || '未处理的 Promise 异常',
      stack: event.reason?.stack,
      trace_id: systemStore.currentTraceID || undefined,
    });
  });

  // 捕获全局 JS 运行时异常
  window.onerror = (message, source, lineno, colno, error): boolean => {
    const systemStore = useSystemStore.getState();
    systemStore.addFrontendError({
      id: generateId(),
      timestamp: Date.now(),
      level: 'CRITICAL',
      source: 'global_runtime',
      message: typeof message === 'string' ? message : '全局运行时异常',
      stack: error?.stack,
      trace_id: systemStore.currentTraceID || undefined,
    });
    // 返回 true 阻止默认浏览器错误处理
    return true;
  };
}
```

### 6.3 异常日志格式与上报通道

前端异常日志**不直接写入后端 PostgreSQL**，而是通过以下两条路径流转：

1.  **本地缓冲（就地查阅）**：写入 `systemStore.frontendErrors`，供诊断面板内的"前端异常"标签页实时查看。环形缓冲，最多保留 100 条。
2.  **异步上报（远程诊断）**：当诊断面板勾选"启用异常上报"时，通过 HTTP `POST /api/v1/telemetry/frontend_errors` 批量上报给 Go Runtime，由 Go 统一写入审计数据库。

```typescript
// frontend/src/renderer/services/telemetryService.ts

import { FrontendErrorEntry } from '../stores/systemStore';
import { useSystemStore } from '../stores/systemStore';

const TELEMETRY_BASE = 'http://127.0.0.1:8080/api/v1/telemetry';

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
```

## 7. 监控诊断面板组件实现

### 7.1 面板入口与布局

```typescript
// frontend/src/renderer/components/Settings/DebugPanel/index.tsx

import React, { useState } from 'react';
import TraceViewer from './TraceViewer';
import AuditLogViewer from './AuditLogViewer';
import MetricsChart from './MetricsChart';
import { useTelemetryStore } from '../../../stores/telemetryStore';
import './DebugPanel.css';

type TabType = 'trace' | 'audit' | 'metrics' | 'errors';

/**
 * DebugPanel: 监控诊断面板主入口
 * 集成四个子标签页：
 * - trace: 链路追踪（按 TraceID 查询）
 * - audit: 审计日志（分页/筛选）
 * - metrics: 监控指标曲线（CPU/Token）
 * - errors: 前端异常日志
 */
const DebugPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('trace');
  const isOpen = useTelemetryStore((s) => s.isOpen);

  if (!isOpen) return null;

  const tabs: { key: TabType; label: string }[] = [
    { key: 'trace', label: '链路追踪' },
    { key: 'audit', label: '审计日志' },
    { key: 'metrics', label: '监控指标' },
    { key: 'errors', label: '前端异常' },
  ];

  return (
    <div className="debug-panel">
      <div className="debug-panel-header">
        <span className="debug-panel-title">诊断面板</span>
        <button
          className="debug-panel-close"
          onClick={() => useTelemetryStore.getState().setOpen(false)}
        >
          ✕
        </button>
      </div>

      {/* 标签页导航 */}
      <div className="debug-panel-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`debug-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 标签页内容 */}
      <div className="debug-panel-content">
        {activeTab === 'trace' && <TraceViewer />}
        {activeTab === 'audit' && <AuditLogViewer />}
        {activeTab === 'metrics' && <MetricsChart />}
        {activeTab === 'errors' && <FrontendErrorViewer />}
      </div>
    </div>
  );
};

/**
 * FrontendErrorViewer: 前端异常日志查看器
 * 展示 systemStore 中缓冲的前端异常记录
 */
const FrontendErrorViewer: React.FC = () => {
  return null; // 详见完整代码
};

export default DebugPanel;
```

### 7.2 链路追踪查看器（TraceViewer）

```typescript
// frontend/src/renderer/components/Settings/DebugPanel/TraceViewer.tsx

import React, { useState, useCallback } from 'react';
import { useTelemetryStore, TelemetrySpan } from '../../../stores/telemetryStore';
import { fetchTraceByID } from '../../../services/telemetryService';

/**
 * TraceViewer: 链路追踪查看器
 * 支持按 TraceID 查询完整调用链，以树形结构展示 Span 的父子关系。
 */
const TraceViewer: React.FC = () => {
  const [inputTraceId, setInputTraceId] = useState('');
  const { currentTraceId, traceSpans, isLoadingTrace, setCurrentTraceId, setTraceSpans, setLoadingTrace } = useTelemetryStore();

  const handleSearch = useCallback(async () => {
    const traceId = inputTraceId.trim();
    if (!traceId) return;

    setCurrentTraceId(traceId);
    setLoadingTrace(true);

    try {
      const spans = await fetchTraceByID(traceId);
      setTraceSpans(spans);
    } catch (err) {
      console.error('获取链路追踪失败:', err);
    } finally {
      setLoadingTrace(false);
    }
  }, [inputTraceId]);

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
          {isLoadingTrace ? '查询中...' : '查询'}
        </button>
      </div>

      {/* 最近 TraceID 快速入口 */}
      {/* ... */}

      {/* Span 树形列表 */}
      <div className="trace-spans">
        {traceSpans.length === 0 && (
          <div className="trace-empty">请输入 TraceID 进行查询</div>
        )}

        {rootSpans.map((span) => (
          <SpanNode
            key={span.span_id}
            span={span}
            allSpans={traceSpans}
            spanMap={spanMap}
            maxDuration={maxDuration}
            depth={0}
          />
        ))}
      </div>
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
}> = ({ span, allSpans, spanMap, maxDuration, depth }) => {
  // 查找子节点
  const children = allSpans.filter((s) => s.parent_span_id === span.span_id);

  return (
    <div className="span-node" style={{ marginLeft: depth * 24 }}>
      <div className={`span-row ${span.status === 'ERROR' ? 'span-error' : ''}`}>
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
        />
      ))}
    </div>
  );
};

export default TraceViewer;
```

### 7.3 审计日志查看器（AuditLogViewer）

```typescript
// frontend/src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx

import React, { useState, useEffect, useCallback } from 'react';
import { useTelemetryStore, AuditLogEntry } from '../../../stores/telemetryStore';
import { fetchAuditLogs } from '../../../services/telemetryService';

/**
 * AuditLogViewer: 审计日志查看器
 * 支持按操作类型、状态、时间范围分页查询。
 */
const AuditLogViewer: React.FC = () => {
  const {
    auditLogs, auditLogTotal, auditLogPage, auditLogPageSize,
    auditLogFilters, isLoadingAuditLogs,
    setAuditLogs, setAuditLogFilter, setAuditLogPage, setLoadingAuditLogs,
  } = useTelemetryStore();

  const loadData = useCallback(async () => {
    setLoadingAuditLogs(true);
    try {
      const result = await fetchAuditLogs({
        page: auditLogPage,
        pageSize: auditLogPageSize,
        ...auditLogFilters,
      });
      setAuditLogs(result.data, result.total);
    } finally {
      setLoadingAuditLogs(false);
    }
  }, [auditLogPage, auditLogPageSize, auditLogFilters]);

  // 首次加载或筛选条件变化时重载
  useEffect(() => {
    loadData();
  }, [loadData]);

  const totalPages = Math.ceil(auditLogTotal / auditLogPageSize);

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
          {auditLogs.map((log) => (
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
```

### 7.4 监控指标曲线图（MetricsChart）

```typescript
// frontend/src/renderer/components/Settings/DebugPanel/MetricsChart.tsx

import React, { useEffect, useRef } from 'react';
import { useTelemetryStore } from '../../../stores/telemetryStore';
import { fetchMetrics } from '../../../services/telemetryService';

/**
 * MetricsChart: 监控指标曲线图
 * 使用原生 Canvas 或轻量级图表库绘制 CPU/内存/协程数/Token 消耗趋势。
 * 数据来源：Go Runtime 内存中的 Ring Buffer（通过 HTTP API 拉取）。
 */
const MetricsChart: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { metrics, metricsRange, isLoadingMetrics, setMetrics, setMetricsRange, setLoadingMetrics } = useTelemetryStore();

  // 切换时间范围时重新拉取
  useEffect(() => {
    const loadMetrics = async () => {
      setLoadingMetrics(true);
      try {
        const data = await fetchMetrics(metricsRange);
        setMetrics(data);
      } finally {
        setLoadingMetrics(false);
      }
    };
    loadMetrics();
  }, [metricsRange]);

  // 绘制 CPU 曲线
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

    const maxCpu = Math.max(...metrics.map((m) => m.cpu_percent), 10);
    const minCpu = 0;

    ctx.strokeStyle = '#4fc3f7';
    ctx.lineWidth = 2;
    ctx.beginPath();

    metrics.forEach((point, index) => {
      const x = padding.left + (index / (metrics.length - 1)) * plotWidth;
      const y = padding.top + plotHeight - ((point.cpu_percent - minCpu) / (maxCpu - minCpu)) * plotHeight;

      index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });

    ctx.stroke();
  }, [metrics]);

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
        <button className="active">CPU 使用率</button>
        <button>内存 (MB)</button>
        <button>协程数</button>
        <button>Token 消耗</button>
        <button>工具失败率</button>
      </div>

      {/* 曲线图区域 */}
      <canvas ref={canvasRef} width={600} height={300} style={{ width: '100%', height: 300 }} />

      {isLoadingMetrics && <div className="metrics-loading">加载中...</div>}
    </div>
  );
};

export default MetricsChart;
```

## 8. Telemetry HTTP API 数据拉取服务

```typescript
// frontend/src/renderer/services/telemetryService.ts

import { TelemetrySpan, AuditLogEntry, MetricsDataPoint } from '../stores/telemetryStore';

const TELEMETRY_BASE = 'http://127.0.0.1:8080/api/v1/telemetry';

/**
 * 按 TraceID 查询链路 Spans
 */
export async function fetchTraceByID(traceId: string): Promise<TelemetrySpan[]> {
  const response = await fetch(`${TELEMETRY_BASE}/traces/${encodeURIComponent(traceId)}`, {
    signal: AbortSignal.timeout(5000), // 5 秒超时
  });

  if (!response.ok) {
    throw new Error(`获取链路追踪失败: ${response.status}`);
  }

  const json = await response.json();
  return json.spans as TelemetrySpan[];
}

/**
 * 查询审计日志（支持分页和筛选）
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
  query.set('page', String(params.page));
  query.set('page_size', String(params.pageSize));
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
  return { data: json.data as AuditLogEntry[], total: json.total as number };
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
  return json.data as MetricsDataPoint[];
}
```

## 9. 前端 UI 架构与 Go Runtime 交互协议定义

### 9.1 新增 WebSocket 消息类型

在 [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts) 中新增以下常量：

```typescript
export const WS_MSG_TYPE = {
  // ... 现有的消息类型 ...

  // === Phase 4 新增：可观测性相关 ===

  // Go -> Electron: 链路 Span 数据（启用诊断面板时推送）
  EVT_TELEMETRY_TRACE: "EVT_TELEMETRY_TRACE",

  // Go -> Electron: 监控指标数据点（启用诊断面板时每秒推送）
  EVT_TELEMETRY_METRICS: "EVT_TELEMETRY_METRICS",

  // Electron -> Go: 启用/禁用实时追踪推送
  CMD_SET_TELEMETRY_MODE: "CMD_SET_TELEMETRY_MODE",
} as const;
```

### 9.2 诊断面板启用/禁用消息协议

```typescript
// Electron -> Go: 启用诊断面板的实时追踪推送
{
  "type": "CMD_SET_TELEMETRY_MODE",
  "trace_id": "tr-1234567890",
  "payload": {
    "enabled": true,
    "push_interval_ms": 1000     // 监控指标推送间隔
  }
}

// Go -> Electron: 响应
{
  "type": "EVT_TELEMETRY_METRICS",
  "trace_id": "tr-1234567890",
  "payload": {
    "timestamp": 1715000000000,
    "cpu_percent": 23.5,
    "memory_mb": 128.4,
    "goroutines": 42,
    "token_consumption": {
      "openai/gpt-4o": 1500,
      "ollama/llama3": 320
    },
    "tool_failure_rate": 0.02
  }
}

// Go -> Electron: 链路 Span 推送（当 DAG 节点执行/完成时触发）
{
  "type": "EVT_TELEMETRY_TRACE",
  "trace_id": "tr-1234567890",
  "payload": {
    "span_id": "span-9876543210",
    "trace_id": "tr-1234567890",
    "parent_span_id": null,
    "name": "DAG_Node_Execute",
    "service": "go_runtime",
    "start_time": "2025-05-06T12:00:00.000Z",
    "end_time": "2025-05-06T12:00:01.200Z",
    "duration_ms": 1200,
    "status": "OK",
    "attributes": {
      "node_id": "node-001",
      "plan_id": "plan-001"
    }
  }
}
```

## 10. 分段实施计划

### Phase 4.1：基础埋点与上下文传递（1-2 天）

**目标**：TraceID 贯穿前端所有 WebSocket 消息，建立异常捕获机制。

- [x] 修改 [`wsManager.ts`](frontend/src/renderer/services/wsManager.ts) `send()` 方法，使用 `systemStore.currentTraceID` 作为 TraceID 源
- [ ] 实现 `useTraceContext` Hook，在用户交互组件中自动管理 TraceID 生命周期
- [ ] 在 `handleMessage()` 中增加 TraceID 自动同步逻辑
- [ ] 实现 `ErrorBoundary` 组件，包裹核心视图区（ChatView、Live2DView）
- [ ] 在 `index.tsx` 入口挂载全局异常监听（`onerror`, `onunhandledrejection`）
- [ ] 扩展 `systemStore`，增加 `frontendErrors` 环形缓冲和相关 actions

### Phase 4.2：诊断面板核心功能（2-3 天）

**目标**：实现链路追踪查看器和审计日志查看器。

- [ ] 创建 `telemetryStore`，定义 `TelemetrySpan`、`AuditLogEntry`、`MetricsDataPoint` 类型
- [ ] 实现 `telemetryService.ts`，封装 `fetchTraceByID`、`fetchAuditLogs` 等 HTTP API
- [ ] 实现 `TraceViewer` 组件：搜索栏 + Span 树形列表
- [ ] 实现 `AuditLogViewer` 组件：筛选栏 + 表格 + 分页
- [ ] 实现诊断面板入口 `DebugPanel/index.tsx`，集成标签页切换

### Phase 4.3：监控指标与实时推送（2-3 天）

**目标**：实现监控指标曲线图和诊断模式的实时推送。

- [ ] 在 `enum.ts` 中增加 `CMD_SET_TELEMETRY_MODE`、`EVT_TELEMETRY_METRICS`、`EVT_TELEMETRY_TRACE` 消息类型
- [ ] 在 `wsManager.ts` 中增加 `EVT_TELEMETRY_METRICS` 和 `EVT_TELEMETRY_TRACE` 的 case 处理
- [ ] 实现 `MetricsChart` 组件：Canvas 绘制 + 时间范围切换
- [ ] 实现诊断面板启用/禁用时发送 `CMD_SET_TELEMETRY_MODE` 指令
- [ ] 实现 `FrontendErrorViewer` 组件：展示前端异常缓冲列表

### Phase 4.4：异常上报与集成收尾（1-2 天）

**目标**：前端异常上报通道打通，整体联调测试。

- [ ] 实现 `uploadFrontendErrors()` 批量上报功能
- [ ] 实现 `startErrorUploadTimer()` 定期上报机制
- [ ] 诊断面板 CSS 样式实现（暗色主题，与 Luna UI 风格一致）
- [ ] 与 Go Runtime 端联调：验证 `CMD_SET_TELEMETRY_MODE` -> `EVT_TELEMETRY_METRICS` 链路
- [ ] 与 PostgreSQL 端联调：验证 TraceID 从前端到后端全链路贯通

## 11. 性能注意事项

1.  **诊断面板默认关闭**：所有实时追踪推送（`EVT_TELEMETRY_TRACE`、`EVT_TELEMETRY_METRICS`）在诊断面板关闭时**不**向 Go 订阅，避免不必要的 WebSocket 流量和渲染压力。
2.  **Canvas 轻量绘图**：监控指标曲线使用原生 Canvas 绘制，避免引入重型图表库，减少渲染开销。Canvas 刷新频率控制在 1Hz（每秒 1 帧）。
3.  **审计日志懒加载**：审计日志查看器仅在切换到"审计日志"标签页时才首次拉取数据，不在后台预加载。
4.  **异常缓冲上限**：`frontendErrors` 使用环形缓冲，最多保留 100 条。超出时从队首丢弃，防止内存泄漏。
