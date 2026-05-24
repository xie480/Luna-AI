package api

import (
	"encoding/json"
	"net/http"
	"time"

	"luna-ai/backend/runtime/internal/types"
)

// HealthResponse 健康检查响应数据
type HealthResponse struct {
	Status    string `json:"status"`
	Service   string `json:"service"`
	Version   string `json:"version"`
	Timestamp string `json:"timestamp"`
}

// HealthCheckHandler 处理健康检查请求
func HealthCheckHandler(w http.ResponseWriter, r *http.Request) {
	data := HealthResponse{
		Status:    "ok",
		Service:   "luna-runtime",
		Version:   "0.1.0",
		Timestamp: time.Now().UTC().Format(time.RFC3339),
	}

	resp := types.NewSuccessResponse(data, r.Header.Get("X-Trace-ID"))

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(resp)
}
