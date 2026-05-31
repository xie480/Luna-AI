package telemetry

import (
	"context"
	"encoding/json"
	"time"

	"gorm.io/gorm"
	"luna-ai/backend/runtime/internal/logger"
)

// Worker 可观测性后台 Worker
// 负责消费 Channel 中的 Span 和 Audit 事件，批量写入 PostgreSQL。
type Worker struct {
	db        *gorm.DB
	spanCh    chan *TraceSpan
	auditCh   chan *AuditLog
	batchSize int
	flushIntv time.Duration
}

// NewWorker 创建一个新的 Telemetry Worker
func NewWorker(db *gorm.DB, batchSize int, flushIntv time.Duration) *Worker {
	return &Worker{
		db:        db,
		spanCh:    make(chan *TraceSpan, 10000),
		auditCh:   make(chan *AuditLog, 10000),
		batchSize: batchSize,
		flushIntv: flushIntv,
	}
}

// RecordSpanAsync 异步记录 Span
func (w *Worker) RecordSpanAsync(span *TraceSpan) {
	select {
	case w.spanCh <- span:
	default:
		logger.Warn(context.Background(), "Telemetry span channel full, dropping span", "span_id", span.SpanID)
	}
}

// RecordAuditLogAsync 异步记录审计日志
func (w *Worker) RecordAuditLogAsync(audit *AuditLog) {
	select {
	case w.auditCh <- audit:
	default:
		logger.Warn(context.Background(), "Telemetry audit channel full, dropping audit log", "audit_id", audit.ID)
	}
}

// UpdateAuditLogAsync 异步更新审计日志状态
func (w *Worker) UpdateAuditLogAsync(id string, status string, errMsg string) {
	// 为了简单起见，这里直接异步执行更新，不走 batch
	go func() {
		err := w.db.Model(&AuditLog{}).Where("id = ?", id).Updates(map[string]interface{}{
			"status":    status,
			"error_msg": errMsg,
		}).Error
		if err != nil {
			logger.Error(context.Background(), "Failed to update audit log", "audit_id", id, "error", err)
		}
	}()
}

// Run 启动 Worker 主循环
func (w *Worker) Run(ctx context.Context) {
	spanBatch := make([]*TraceSpan, 0, w.batchSize)
	auditBatch := make([]*AuditLog, 0, w.batchSize)
	ticker := time.NewTicker(w.flushIntv)
	defer ticker.Stop()

	for {
		select {
		case span := <-w.spanCh:
			spanBatch = append(spanBatch, span)
			if len(spanBatch) >= w.batchSize {
				w.flushSpans(ctx, spanBatch)
				spanBatch = spanBatch[:0]
			}
		case audit := <-w.auditCh:
			auditBatch = append(auditBatch, audit)
			if len(auditBatch) >= w.batchSize {
				w.flushAuditLogs(ctx, auditBatch)
				auditBatch = auditBatch[:0]
			}
		case <-ticker.C:
			if len(spanBatch) > 0 {
				w.flushSpans(ctx, spanBatch)
				spanBatch = spanBatch[:0]
			}
			if len(auditBatch) > 0 {
				w.flushAuditLogs(ctx, auditBatch)
				auditBatch = auditBatch[:0]
			}
		case <-ctx.Done():
			w.flushSpans(context.Background(), spanBatch)
			w.flushAuditLogs(context.Background(), auditBatch)
			return
		}
	}
}

func (w *Worker) flushSpans(ctx context.Context, batch []*TraceSpan) {
	if len(batch) == 0 {
		return
	}
	if err := w.db.WithContext(ctx).CreateInBatches(batch, len(batch)).Error; err != nil {
		logger.Error(ctx, "Failed to flush trace spans", "error", err, "count", len(batch))
		// 降级：写入失败时转写本地应急文件 (这里简化处理，仅打印日志)
		fallbackLog("span", batch)
	}
}

func (w *Worker) flushAuditLogs(ctx context.Context, batch []*AuditLog) {
	if len(batch) == 0 {
		return
	}
	if err := w.db.WithContext(ctx).CreateInBatches(batch, len(batch)).Error; err != nil {
		logger.Error(ctx, "Failed to flush audit logs", "error", err, "count", len(batch))
		// 降级：写入失败时转写本地应急文件
		fallbackLog("audit", batch)
	}
}

func fallbackLog(typ string, batch interface{}) {
	data, _ := json.Marshal(batch)
	logger.Error(context.Background(), "FALLBACK_LOG", "type", typ, "data", string(data))
}

// 全局单例
var globalWorker *Worker

// InitWorker 初始化全局 Worker
func InitWorker(db *gorm.DB) {
	globalWorker = NewWorker(db, 100, 500*time.Millisecond)
}

// GetWorker 获取全局 Worker
func GetWorker() *Worker {
	return globalWorker
}
