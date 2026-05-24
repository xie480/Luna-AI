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
// 做什么：处理 /health 路由的 GET 请求，返回服务的健康状态。
// 为什么这样做：提供给外部监控系统或前端确认后端服务是否存活。
// 输入输出：输入 HTTP 请求，输出包含状态、服务名、版本和时间戳的 JSON 响应。
// 边界条件：无特殊边界条件，只要服务能处理请求即返回 ok。
// 异常行为：如果 JSON 编码失败，会静默忽略。
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
