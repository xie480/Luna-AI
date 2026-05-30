package api

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/types"
)

// ComponentHealth 单个组件的健康状态
type ComponentHealth struct {
	// 组件名称
	Name string `json:"name"`
	// 健康状态: healthy, unhealthy, degraded
	Status string `json:"status"`
	// 错误信息（仅在 unhealthy 时有值）
	Message string `json:"message,omitempty"`
	// 响应延迟（毫秒）
	LatencyMs int64 `json:"latency_ms,omitempty"`
}

// HealthResponse 健康检查响应数据
// 包含整体状态和各组件的详细健康状态
type HealthResponse struct {
	// 整体健康状态: healthy, unhealthy, degraded
	Status string `json:"status"`
	// 服务名称
	Service string `json:"service"`
	// 服务版本
	Version string `json:"version"`
	// 时间戳
	Timestamp string `json:"timestamp"`
	// 各组件健康状态详情
	Components []ComponentHealth `json:"components"`
}

// HealthHandler 封装健康检查处理器
// 包含对各基础设施组件的健康检查能力
type HealthHandler struct {
	// AI 服务客户端
	aiClient *AIClient
	// Redis 客户端（可选）
	redisClient *infrastructure.RedisClient
	// PostgreSQL 客户端（可选）
	postgresClient *infrastructure.PostgresClient
}

// NewHealthHandler 创建一个新的 HealthHandler 实例
// 参数:
//   - aiClient: AI 服务 gRPC 客户端
//   - redisClient: Redis 客户端（可为 nil）
//   - postgresClient: PostgreSQL 客户端（可为 nil）
//
// 返回:
//   - *HealthHandler: 健康检查处理器实例
func NewHealthHandler(aiClient *AIClient, redisClient *infrastructure.RedisClient, postgresClient *infrastructure.PostgresClient) *HealthHandler {
	return &HealthHandler{
		aiClient:       aiClient,
		redisClient:    redisClient,
		postgresClient: postgresClient,
	}
}

// HandleHealthCheck 处理健康检查请求
// 做什么：处理 /health 路由的 GET 请求，返回服务及各组件的健康状态。
// 为什么这样做：提供给外部监控系统或前端确认后端服务及各依赖组件是否存活。
// 输入输出：输入 HTTP 请求，输出包含整体状态、服务名、版本、时间戳和各组件状态的 JSON 响应。
// 边界条件：如果某个组件不可用，整体状态为 degraded 或 unhealthy。
// 异常行为：如果 JSON 编码失败，会记录日志并返回 500 错误。
func (h *HealthHandler) HandleHealthCheck(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	traceID := r.Header.Get("X-Trace-ID")

	// 检查各组件健康状态
	components := h.checkComponents(ctx)

	// 计算整体健康状态
	overallStatus := h.calculateOverallStatus(components)

	// 构造响应数据
	data := HealthResponse{
		Status:     overallStatus,
		Service:    "luna-runtime",
		Version:    "0.1.0",
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
		Components: components,
	}

	// 记录健康检查日志
	logger.Info(ctx, "健康检查完成",
		zap.String("trace_id", traceID),
		zap.String("status", overallStatus),
		zap.Int("component_count", len(components)),
	)

	// 构造标准响应
	resp := types.NewSuccessResponse(data, traceID)

	// 设置响应头并返回
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		logger.Error(ctx, "编码健康检查响应失败", zap.Error(err))
	}
}

// checkComponents 检查各组件的健康状态
// 返回各组件的健康状态列表
func (h *HealthHandler) checkComponents(ctx context.Context) []ComponentHealth {
	components := make([]ComponentHealth, 0, 4)

	// 1. 检查 Go Runtime 自身（始终健康）
	components = append(components, ComponentHealth{
		Name:      "go-runtime",
		Status:    types.HealthStatusHealthy,
		LatencyMs: 0,
	})

	// 2. 检查 Python AI 服务
	aiHealth := h.checkAIService(ctx)
	components = append(components, aiHealth)

	// 3. 检查 Redis（如果已初始化）
	if h.redisClient != nil {
		redisHealth := h.checkRedis(ctx)
		components = append(components, redisHealth)
	} else {
		components = append(components, ComponentHealth{
			Name:    "redis",
			Status:  types.HealthStatusDegraded,
			Message: "Redis 客户端未初始化",
		})
	}

	// 4. 检查 PostgreSQL（如果已初始化）
	if h.postgresClient != nil {
		postgresHealth := h.checkPostgres(ctx)
		components = append(components, postgresHealth)
	} else {
		components = append(components, ComponentHealth{
			Name:    "postgres",
			Status:  types.HealthStatusDegraded,
			Message: "PostgreSQL 客户端未初始化",
		})
	}

	return components
}

// checkAIService 检查 Python AI 服务的健康状态
// 通过 gRPC Ping 方法测试连接
func (h *HealthHandler) checkAIService(ctx context.Context) ComponentHealth {
	start := time.Now()

	// 设置超时时间
	checkCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()

	// 发送 Ping 请求
	_, err := h.aiClient.Ping(checkCtx, "health-check")

	latency := time.Since(start).Milliseconds()

	if err != nil {
		logger.Warn(ctx, "AI 服务健康检查失败", zap.Error(err))
		return ComponentHealth{
			Name:      "ai-service",
			Status:    types.HealthStatusUnhealthy,
			Message:   err.Error(),
			LatencyMs: latency,
		}
	}

	return ComponentHealth{
		Name:      "ai-service",
		Status:    types.HealthStatusHealthy,
		LatencyMs: latency,
	}
}

// checkRedis 检查 Redis 的健康状态
// 通过 Ping 方法测试连接
func (h *HealthHandler) checkRedis(ctx context.Context) ComponentHealth {
	start := time.Now()

	// 设置超时时间
	checkCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	isHealthy := h.redisClient.IsHealthy(checkCtx)
	latency := time.Since(start).Milliseconds()

	if !isHealthy {
		return ComponentHealth{
			Name:      "redis",
			Status:    types.HealthStatusUnhealthy,
			Message:   "Redis Ping 失败",
			LatencyMs: latency,
		}
	}

	return ComponentHealth{
		Name:      "redis",
		Status:    types.HealthStatusHealthy,
		LatencyMs: latency,
	}
}

// checkPostgres 检查 PostgreSQL 的健康状态
// 通过 Ping 方法测试连接
func (h *HealthHandler) checkPostgres(ctx context.Context) ComponentHealth {
	start := time.Now()

	// 设置超时时间
	checkCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	isHealthy := h.postgresClient.IsHealthy(checkCtx)
	latency := time.Since(start).Milliseconds()

	if !isHealthy {
		return ComponentHealth{
			Name:      "postgres",
			Status:    types.HealthStatusUnhealthy,
			Message:   "PostgreSQL Ping 失败",
			LatencyMs: latency,
		}
	}

	return ComponentHealth{
		Name:      "postgres",
		Status:    types.HealthStatusHealthy,
		LatencyMs: latency,
	}
}

// calculateOverallStatus 根据各组件状态计算整体健康状态
// 规则:
//   - 所有组件健康 -> healthy
//   - 有组件 unhealthy -> unhealthy
//   - 有组件 degraded 但无 unhealthy -> degraded
func (h *HealthHandler) calculateOverallStatus(components []ComponentHealth) string {
	hasUnhealthy := false
	hasDegraded := false

	for _, comp := range components {
		if comp.Status == types.HealthStatusUnhealthy {
			hasUnhealthy = true
		}
		if comp.Status == types.HealthStatusDegraded {
			hasDegraded = true
		}
	}

	if hasUnhealthy {
		return types.HealthStatusUnhealthy
	}
	if hasDegraded {
		return types.HealthStatusDegraded
	}
	return types.HealthStatusHealthy
}
