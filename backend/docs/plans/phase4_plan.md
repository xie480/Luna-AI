# Phase 4: 最小可观测性与审计链路实施方案

## 1. 整体系统架构拓扑

Luna 的可观测性架构以 **Go Runtime 为核心控制面与数据汇聚中心**，采用轻量级本地化方案，实现 Electron、Go、Python 三层的全链路追踪与审计。

*   **Electron (UI 层)**：作为链路起点，在发起 WebSocket 请求时生成或携带 `TraceID`。负责渲染诊断面板，展示链路回放与审计日志。
*   **Go Runtime (调度层)**：
    *   **日志与追踪网关**：拦截所有进出请求，生成全局唯一的 `TraceID`（基于 Snowflake 算法）。
    *   **状态与指标汇聚**：维护内存中的监控指标（Ring Buffer），异步批量将链路跨度（Spans）和审计日志（Audit Logs）写入本地 PostgreSQL。
    *   **文件日志轮转**：将常规运行日志写入本地文件系统并进行轮转管理。
*   **Python AI Service (智能层)**：
    *   通过 gRPC 拦截器提取 `TraceID`，利用 `contextvars` 绑定到当前执行上下文。
    *   执行正则脱敏后，将关键推理日志、Token 消耗等指标通过 gRPC 响应或异步回调回传给 Go。

## 2. 技术栈选型与核心中间件集成

*   **Go 侧技术栈**：
    *   **日志库**：标准库 `log/slog`，提供高性能的结构化 JSON 日志。
    *   **日志轮转**：`gopkg.in/natefinch/lumberjack.v2`，实现按大小、时间、保留天数的文件轮转。
    *   **本地存储**：`github.com/jackc/pgx/v5`，使用 PostgreSQL 数据库，利用连接池（pgxpool）提升并发写性能。
    *   **ID 生成**：项目统一的 Snowflake 算法实现。
*   **Python 侧技术栈**：
    *   **日志库**：`loguru`，支持便捷的上下文绑定（`contextualize`）和结构化输出。
    *   **上下文管理**：标准库 `contextvars`，在异步和多线程环境中安全传递 `TraceID`。
*   **中间件集成方式**：
    *   **Go gRPC Client Interceptor**：在调用 Python 服务前，自动将 `TraceID` 注入 gRPC Metadata (`x-trace-id`)。
    *   **Python gRPC Server Interceptor**：拦截请求，提取 Metadata 中的 `TraceID` 并设置到 `contextvars`。
    *   **Go MCP Tool Middleware**：在工具执行引擎层包装一层守卫，强制记录入参（脱敏后）、执行耗时和结果到审计表。

## 3. 日志收集与动态分级策略

### 3.1 动态分级策略
系统支持 `DEBUG`, `INFO`, `WARN`, `ERROR` 四个级别。
*   **热更新**：Go 侧维护一个原子的 `slog.LevelVar`，当监听到配置变更事件（Event Bus）时，动态调整日志级别，无需重启服务。

### 3.2 隔离与落盘策略
*   **常规流日志 (App Logs)**：
    *   存储路径：`logs/luna-app.log`, `logs/luna-python.log`。
    *   轮转策略：单文件最大 10MB，保留最近 5 个备份，最多保留 7 天。
*   **审计日志 (Audit Logs)**：
    *   存储介质：PostgreSQL `audit_logs` 表。
    *   记录范围：所有 `MEDIUM` 和 `HIGH` 风险的工具调用、系统状态跃迁、用户授权结果。
*   **链路追踪 (Trace Spans)**：
    *   存储介质：PostgreSQL `trace_spans` 表。
    *   记录范围：DAG 节点执行耗时、LLM 推理耗时、网络请求耗时。

### 3.3 数据脱敏策略 (Sanitization)
*   **Python 侧**：在发往 LLM 的 Prompt 和接收的 Response 记录日志前，通过正则匹配（如 `sk-[a-zA-Z0-9]+`）将 API Key、Token 等替换为 `[REDACTED]`。
*   **Go 侧**：在记录工具调用的 Payload 时，针对特定工具（如环境变量读取、凭证管理）的参数进行掩码处理。

## 4. 分布式链路追踪机制

采用轻量级的 Span 模型，不引入沉重的 Jaeger/Zipkin，但保留数据结构的兼容性。

1.  **TraceID 生成**：Electron 发起请求时若无 `TraceID`，Go WebSocket 网关使用 Snowflake 生成一个全局唯一的 `TraceID`。
2.  **Span 树构建**：
    *   Go 侧在开始处理意图时创建 Root Span。
    *   进入 DAG 节点时创建 Child Span。
    *   调用 Python 服务时，通过 gRPC Metadata 传递 `TraceID` 和 `ParentSpanID`。
    *   Python 侧在进行 LLM 推理时创建孙级 Span，记录 Token 消耗。
3.  **闭环收集**：Python 侧的 Span 数据随 gRPC 响应的扩展字段返回，或通过独立的 Telemetry RPC 异步上报给 Go，由 Go 统一落盘。

## 5. 核心监控指标采集方案

Go Runtime 在内存中维护一个基于时间滑动的 Ring Buffer，用于存储最近 24 小时（按分钟聚合，共 1440 个数据点）的监控指标，供前端诊断面板实时拉取。

*   **采集指标**：
    *   `system_cpu_usage` / `system_memory_usage`：系统资源占用。
    *   `go_goroutines_count`：Go 协程数量（防泄漏监控）。
    *   `llm_token_consumption`：按模型 Provider 分类的 Token 消耗速率。
    *   `tool_call_failure_rate`：工具调用失败率。
*   **采集方式**：Go 侧启动一个后台 Ticker 协程，每分钟采集一次当前状态并压入 Ring Buffer。

## 6. 数据审计追踪模型与数据库表结构

数据库：`luna_telemetry` (PostgreSQL)

### 6.1 审计日志表 (`audit_logs`)
```sql
CREATE TABLE audit_logs (
    id VARCHAR(64) PRIMARY KEY,          -- Snowflake ID
    trace_id VARCHAR(64) NOT NULL,       -- 关联的 TraceID
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    plan_id VARCHAR(64),                 -- 关联的 DAG Plan
    node_id VARCHAR(64),                 -- 关联的 DAG Node
    action_type VARCHAR(32) NOT NULL,    -- 'TOOL_CALL', 'MEMORY_COMMIT', 'STATE_CHANGE'
    resource VARCHAR(128),               -- 操作的资源，如文件路径
    operation VARCHAR(128) NOT NULL,     -- 具体操作，如 'os.execute_script'
    payload JSONB,                       -- 脱敏后的入参（PostgreSQL 原生 JSONB 类型）
    risk_level VARCHAR(16) NOT NULL,     -- 'LOW', 'MEDIUM', 'HIGH'
    status VARCHAR(32) NOT NULL,         -- 'SUCCESS', 'FAILED', 'DENIED', 'TIMEOUT'
    error_msg TEXT,                      -- 失败原因
    requires_approval BOOLEAN,           -- 是否触发了 Gating
    user_approved BOOLEAN                -- 用户是否同意
);
CREATE INDEX idx_audit_trace ON audit_logs(trace_id);
CREATE INDEX idx_audit_time ON audit_logs(timestamp);
```

### 6.2 链路跨度表 (`trace_spans`)
```sql
CREATE TABLE trace_spans (
    span_id VARCHAR(64) PRIMARY KEY,     -- Snowflake ID
    trace_id VARCHAR(64) NOT NULL,
    parent_span_id VARCHAR(64),
    name VARCHAR(128) NOT NULL,          -- Span 名称，如 'LLM_Reasoning'
    service VARCHAR(32) NOT NULL,        -- 'electron', 'go_runtime', 'python_ai'
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_ms INTEGER,
    status VARCHAR(16),                  -- 'OK', 'ERROR'
    attributes JSONB                     -- 扩展属性，如 {'tokens_used': 150}
);
CREATE INDEX idx_span_trace ON trace_spans(trace_id);
```

### 6.3 数据保留与清理策略
审计日志和链路追踪数据不应无限增长，通过 PostgreSQL 定时任务进行运维管理：

```sql
-- 审计日志：保留最近 3 个月
CREATE OR REPLACE FUNCTION cleanup_audit_logs()
RETURNS void AS $$
BEGIN
    DELETE FROM audit_logs WHERE timestamp < NOW() - INTERVAL '3 months';
END;
$$ LANGUAGE plpgsql;

-- 链路跨度：保留最近 7 天（调试/诊断场景）
CREATE OR REPLACE FUNCTION cleanup_trace_spans()
RETURNS void AS $$
BEGIN
    DELETE FROM trace_spans WHERE start_time < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;
```

Go Runtime 启动后台 Cron Worker，定期执行上述清理函数，避免表数据无限膨胀。

## 7. 关键 API 接口规范

提供给 Electron 前端诊断面板的 HTTP 接口：

*   **获取链路详情**
    *   `GET /api/v1/telemetry/traces/:trace_id`
    *   返回该 Trace 下的所有 Spans，按父子关系组织。
*   **查询审计日志**
    *   `GET /api/v1/telemetry/audit_logs?limit=50&offset=0&action_type=TOOL_CALL&status=FAILED`
    *   支持按类型、状态、时间范围分页查询。
*   **获取实时监控指标**
    *   `GET /api/v1/telemetry/metrics?range=1h`
    *   返回 Ring Buffer 中聚合的监控数据点，用于前端绘制 ECharts 曲线。

## 8. 核心拦截器与中间件伪代码实现

### 8.1 Go: slog Context Handler (低侵入性日志)
```go
// ContextHandler 装饰 slog.Handler，自动从 context.Context 中提取
// TraceID、NodeID 等关键标识符并注入日志记录。
type ContextHandler struct {
    slog.Handler
}

func (h *ContextHandler) Handle(ctx context.Context, r slog.Record) error {
    if traceID, ok := ctx.Value(constants.TraceIDKey).(string); ok {
        r.AddAttrs(slog.String("trace_id", traceID))
    }
    if nodeID, ok := ctx.Value(constants.NodeIDKey).(string); ok {
        r.AddAttrs(slog.String("node_id", nodeID))
    }
    if taskID, ok := ctx.Value(constants.TaskIDKey).(string); ok {
        r.AddAttrs(slog.String("task_id", taskID))
    }
    return h.Handler.Handle(ctx, r)
}
```

### 8.2 Go: gRPC Client Interceptor (Trace 传递)
```go
// TelemetryUnaryClientInterceptor gRPC 客户端拦截器
// 自动从 context 提取 TraceID 注入 gRPC Metadata，并记录调用 Span。
func TelemetryUnaryClientInterceptor() grpc.UnaryClientInterceptor {
    return func(ctx context.Context, method string, req, reply interface{},
        cc *grpc.ClientConn, invoker grpc.UnaryInvoker, opts ...grpc.CallOption) error {

        traceID, _ := ctx.Value(constants.TraceIDKey).(string)
        spanID := snowflake.GenerateStringID()

        // 将 TraceID 和 ParentSpanID 注入 gRPC Metadata
        md := metadata.Pairs("x-trace-id", traceID, "x-parent-span-id", spanID)
        ctx = metadata.NewOutgoingContext(ctx, md)

        startTime := time.Now()
        err := invoker(ctx, method, req, reply, cc, opts...)
        duration := time.Since(startTime)

        // 异步记录 Span：通过 Channel 投递，由后台 Worker 批量写入 PostgreSQL
        telemetry.RecordSpanAsync(telemetry.SpanEvent{
            TraceID:    traceID,
            SpanID:     spanID,
            Name:       method,
            Service:    "go_runtime",
            StartTime:  startTime,
            DurationMs: duration.Milliseconds(),
            Status:     statusFromError(err),
            Attributes: extractLLMAttributes(reply),
        })
        return err
    }
}
```

### 8.3 Go: MCP Tool Execution Middleware (审计拦截)
```go
// AuditToolMiddleware MCP 工具执行中间件
// 包装工具执行器，强制进行参数脱敏和审计日志记录。
func AuditToolMiddleware(next ToolExecutor) ToolExecutor {
    return func(ctx context.Context, tool Tool, args map[string]interface{}) (interface{}, error) {
        traceID, _ := ctx.Value(constants.TraceIDKey).(string)

        // 步骤1：对敏感参数进行脱敏
        sanitizedArgs := SanitizeArgs(tool.Name, args)

        // 步骤2：记录审计前置事件（Write-Ahead：先记日志再执行）
        auditEntry := &AuditLog{
            TraceID:   traceID,
            Action:    "TOOL_CALL",
            Resource:  tool.Resource,
            Operation: tool.Name,
            Payload:   sanitizedArgs,
            RiskLevel: tool.RiskLevel,
            Status:    "PENDING",
        }
        telemetry.RecordAuditLogAsync(auditEntry)

        // 步骤3：执行工具（可能触发 Gating 挂起）
        result, err := next(ctx, tool, args)

        // 步骤4：更新审计日志执行结果
        status := "SUCCESS"
        errMsg := ""
        if err != nil {
            status = "FAILED"
            errMsg = err.Error()
            if errors.Is(err, ErrSecurityViolation) || errors.Is(err, ErrUserRejected) {
                status = "DENIED"
            }
        }
        telemetry.UpdateAuditLogAsync(auditEntry.ID, status, errMsg)

        return result, err
    }
}
```

### 8.4 Python: gRPC Server Interceptor & Loguru 上下文绑定
```python
import contextvars
from loguru import logger
import grpc

# 上下文变量，用于在异步/多线程环境中安全传递 TraceID
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="UNKNOWN")

class TelemetryInterceptor(grpc.ServerInterceptor):
    """gRPC 服务端拦截器：提取 Go 侧注入的 TraceID 并绑定到 Loguru 上下文。"""

    def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata)
        trace_id = metadata.get("x-trace-id", "UNKNOWN")
        parent_span_id = metadata.get("x-parent-span-id", "")

        # 设置 contextvars，使同一协程内任意位置都能获取 TraceID
        token = trace_id_var.set(trace_id)

        try:
            # 绑定 loguru 上下文，后续所有日志自动携带 trace_id 字段
            with logger.contextualize(trace_id=trace_id, parent_span_id=parent_span_id):
                logger.info("收到 gRPC 请求", handler=handler_call_details.method)
                return continuation(handler_call_details)
        except Exception as e:
            logger.error("gRPC 处理异常", error=str(e))
            raise
        finally:
            trace_id_var.reset(token)
```

### 8.5 Go: 异步批量写入 Worker (PostgreSQL Batch Insert)
```go
// TelemetryWorker 可观测性后台 Worker
// 负责消费 Channel 中的 Span 和 Audit 事件，批量写入 PostgreSQL。
type TelemetryWorker struct {
    spanCh    chan SpanEvent      // Span 事件管道
    auditCh   chan AuditLogEvent  // 审计日志事件管道
    batchSize int                 // 批量提交阈值
    flushIntv time.Duration       // 最大刷新间隔
}

// Run 启动 Worker 主循环
func (w *TelemetryWorker) Run(ctx context.Context, pool *pgxpool.Pool) {
    spanBatch := make([]SpanEvent, 0, w.batchSize)
    auditBatch := make([]AuditLogEvent, 0, w.batchSize)
    ticker := time.NewTicker(w.flushIntv)
    defer ticker.Stop()

    for {
        select {
        case span := <-w.spanCh:
            spanBatch = append(spanBatch, span)
            if len(spanBatch) >= w.batchSize {
                w.flushSpans(ctx, pool, spanBatch)
                spanBatch = spanBatch[:0]
            }
        case audit := <-w.auditCh:
            auditBatch = append(auditBatch, audit)
            if len(auditBatch) >= w.batchSize {
                w.flushAuditLogs(ctx, pool, auditBatch)
                auditBatch = auditBatch[:0]
            }
        case <-ticker.C:
            // 定时刷出剩余未满批次的数据
            if len(spanBatch) > 0 {
                w.flushSpans(ctx, pool, spanBatch)
                spanBatch = spanBatch[:0]
            }
            if len(auditBatch) > 0 {
                w.flushAuditLogs(ctx, pool, auditBatch)
                auditBatch = auditBatch[:0]
            }
        case <-ctx.Done():
            // 退出前最后一次刷出
            w.flushSpans(ctx, pool, spanBatch)
            w.flushAuditLogs(ctx, pool, auditBatch)
            return
        }
    }
}

// flushSpans 批量插入 Span 到 PostgreSQL
func (w *TelemetryWorker) flushSpans(ctx context.Context, pool *pgxpool.Pool, batch []SpanEvent) {
    // 使用 pgx.CopyFrom 实现高效批量写入
    rows := make([][]interface{}, len(batch))
    for i, s := range batch {
        rows[i] = []interface{}{s.SpanID, s.TraceID, s.ParentSpanID, s.Name,
            s.Service, s.StartTime, s.EndTime, s.DurationMs, s.Status, s.Attributes}
    }
    _, err := pool.CopyFrom(ctx, pgx.Identifier{"trace_spans"},
        []string{"span_id", "trace_id", "parent_span_id", "name", "service",
            "start_time", "end_time", "duration_ms", "status", "attributes"},
        pgx.CopyFromRows(rows))
    if err != nil {
        // 降级：写入失败时转写本地应急文件
        writeFallbackLog("span", batch)
    }
}
```

## 9. 性能保障、低侵入性与数据一致性

### 9.1 低侵入性设计
*   **隐式上下文传递**：业务代码无需手动传递 `TraceID`，只需将 `context.Context` 传入标准日志方法（如 `slog.InfoContext`），底层 Handler 会自动提取并附加字段。
*   **AOP 模式**：通过 gRPC 拦截器和工具执行中间件，将追踪和审计逻辑与核心业务逻辑完全解耦。业务开发人员只需关注工具的具体执行逻辑，无需关心日志和审计的采集细节。

### 9.2 高并发场景下的性能保障
*   **异步批量写入 (Batch Insert)**：Go 侧严禁在业务协程中同步执行 PostgreSQL `INSERT`。采用 Channel 接收日志事件，由独立的 Worker 协程进行批量插入（如每 100 条或每 500ms 提交一次事务），优先使用 `pgx.CopyFrom` 实现 PostgreSQL 原生高速批量导入，极大降低连接占用与锁竞争。
*   **PostgreSQL 连接池**：通过 pgxpool 配置合理的连接池大小（默认 `max_conns=10`），利用 PostgreSQL 原生的 MVCC 机制允许读写并发，提升本地数据库吞吐量。审计日志与业务数据共享同一个 PostgreSQL 实例，但通过独立的连接池配置隔离负载。
*   **无锁 Ring Buffer**：监控指标的内存存储采用预分配的环形队列，使用原子操作（`atomic`）推进读写指针，避免频繁的内存分配和 GC 压力。

### 9.3 审计数据的完整性与一致性
*   **降级策略 (Fallback)**：如果 PostgreSQL 出现连接池耗尽、死锁或磁盘满等极端情况，后台 Worker 会触发降级，将审计日志转写到本地纯文本文件 `fallback_audit.log`，确保高危操作记录不丢失。系统恢复正常后，可手动将应急日志回灌至数据库。
*   **异常闭环补齐**：如果 Python 进程崩溃（Segfault/OOM）导致未返回 Span 结束信号，Go 侧的 gRPC 调用会超时或报错。此时 Go 侧的 Interceptor 会自动为该 `TraceID` 补齐一个 `Status: ERROR` 的 Span，备注 `Python Runtime Unexpected Exit`，保证追踪树的完整闭环。
*   **Write-Ahead 审计策略**：审计日志的写入先于实际的高危副作用操作（先写 PENDING 状态，后更新为 SUCCESS/FAILED）。如果系统在执行高危操作时断电，重启后可通过比对审计日志中残留的 PENDING 记录与实际状态发现异常。
