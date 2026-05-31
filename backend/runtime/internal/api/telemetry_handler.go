package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"gorm.io/gorm"
	"luna-ai/backend/runtime/internal/telemetry"
	"luna-ai/backend/runtime/internal/types"
)

// TelemetryHandler 处理可观测性相关的 HTTP 请求
type TelemetryHandler struct {
	db *gorm.DB
}

// NewTelemetryHandler 创建一个新的 TelemetryHandler
func NewTelemetryHandler(db *gorm.DB) *TelemetryHandler {
	return &TelemetryHandler{
		db: db,
	}
}

// GetTraces 获取链路详情
// GET /api/v1/telemetry/traces
func (h *TelemetryHandler) GetTraces(w http.ResponseWriter, r *http.Request) {
	query := h.db.Model(&telemetry.TraceSpan{})

	if traceID := r.URL.Query().Get("trace_id"); traceID != "" {
		query = query.Where("trace_id = ?", traceID)
	}

	// 分页
	limit := 50
	if l := r.URL.Query().Get("limit"); l != "" {
		if parsedLimit, err := strconv.Atoi(l); err == nil && parsedLimit > 0 {
			limit = parsedLimit
		}
	}
	offset := 0
	if o := r.URL.Query().Get("offset"); o != "" {
		if parsedOffset, err := strconv.Atoi(o); err == nil && parsedOffset >= 0 {
			offset = parsedOffset
		}
	}

	var spans []telemetry.TraceSpan
	var total int64

	query.Count(&total)
	if err := query.Order("start_time DESC").Limit(limit).Offset(offset).Find(&spans).Error; err != nil {
		http.Error(w, "Failed to fetch traces", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(types.Response{
		Code: types.CodeSuccess,
		Data: map[string]interface{}{
			"total": total,
			"spans": spans,
		},
	})
}

// GetAuditLogs 查询审计日志
// GET /api/v1/telemetry/audit_logs?limit=50&offset=0&action_type=TOOL_CALL&status=FAILED
func (h *TelemetryHandler) GetAuditLogs(w http.ResponseWriter, r *http.Request) {
	query := h.db.Model(&telemetry.AuditLog{})

	// 解析查询参数
	if actionType := r.URL.Query().Get("action_type"); actionType != "" {
		query = query.Where("action_type = ?", actionType)
	}
	if status := r.URL.Query().Get("status"); status != "" {
		query = query.Where("status = ?", status)
	}
	if traceID := r.URL.Query().Get("trace_id"); traceID != "" {
		query = query.Where("trace_id = ?", traceID)
	}

	// 分页
	limit := 50
	if l := r.URL.Query().Get("limit"); l != "" {
		if parsedLimit, err := strconv.Atoi(l); err == nil && parsedLimit > 0 {
			limit = parsedLimit
		}
	}
	offset := 0
	if o := r.URL.Query().Get("offset"); o != "" {
		if parsedOffset, err := strconv.Atoi(o); err == nil && parsedOffset >= 0 {
			offset = parsedOffset
		}
	}

	var logs []telemetry.AuditLog
	var total int64

	query.Count(&total)
	if err := query.Order("timestamp DESC").Limit(limit).Offset(offset).Find(&logs).Error; err != nil {
		http.Error(w, "Failed to fetch audit logs", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(types.Response{
		Code: types.CodeSuccess,
		Data: map[string]interface{}{
			"total": total,
			"logs":  logs,
		},
	})
}

// GetMetrics 获取实时监控指标
// GET /api/v1/telemetry/metrics?range=1h
func (h *TelemetryHandler) GetMetrics(w http.ResponseWriter, r *http.Request) {
	// 简单实现：返回 RingBuffer 中的所有数据
	// 实际应用中可以根据 range 参数过滤
	buffer := telemetry.GetMetricsBuffer()
	if buffer == nil {
		http.Error(w, "Metrics buffer not initialized", http.StatusInternalServerError)
		return
	}

	// 默认返回最近 60 个点 (1小时)
	n := 60
	if r := r.URL.Query().Get("range"); r == "24h" {
		n = 1440
	}

	points := buffer.GetRecent(n)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(types.Response{
		Code: types.CodeSuccess,
		Data: points,
	})
}
