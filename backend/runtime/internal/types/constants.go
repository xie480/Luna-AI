package types

// WebSocket 消息类型常量
const (
	WSMsgTypePing        = "PING"
	WSMsgTypePong        = "PONG"
	WSMsgTypeChatRequest = "CHAT_REQUEST"
	WSMsgTypeChatStream  = "CHAT_STREAM"
	WSMsgTypeError       = "ERROR"
)

// 健康检查状态常量
const (
	HealthStatusHealthy   = "healthy"
	HealthStatusUnhealthy = "unhealthy"
	HealthStatusDegraded  = "degraded"
)
