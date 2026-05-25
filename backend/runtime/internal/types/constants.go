package types

// WebSocket 消息类型常量
const (
	WSMsgTypePing             = "PING"
	WSMsgTypePong             = "PONG"
	WSMsgTypeChatRequest      = "CHAT_REQUEST"
	WSMsgTypeChatStream       = "CHAT_STREAM"
	WSMsgTypeError            = "ERROR"
	WSMsgTypeCmdSyncInitState = "CMD_SYNC_INIT_STATE"
	WSMsgTypeEvtInitState     = "EVT_INIT_STATE"
)

// 健康检查状态常量
const (
	HealthStatusHealthy   = "healthy"
	HealthStatusUnhealthy = "unhealthy"
	HealthStatusDegraded  = "degraded"
)
