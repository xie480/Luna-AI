package types

// WebSocket 消息类型常量
const (
	WSMsgTypePing             = "PING"
	WSMsgTypePong             = "PONG"
	WSMsgTypeChatStream       = "CHAT_STREAM"
	WSMsgTypeError            = "ERROR"
	WSMsgTypeCmdSyncInitState = "CMD_SYNC_INIT_STATE"
	WSMsgTypeCmdUserInput     = "CMD_USER_INPUT"
	WSMsgTypeEvtInitState     = "EVT_INIT_STATE"
)

// 健康检查状态常量
const (
	HealthStatusHealthy   = "healthy"
	HealthStatusUnhealthy = "unhealthy"
	HealthStatusDegraded  = "degraded"
)

// 角色常量定义
const (
	RoleUser      = "user"
	RoleAssistant = "assistant"
	RoleSystem    = "system"
)
