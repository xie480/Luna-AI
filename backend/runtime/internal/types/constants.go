package types

// WebSocket 消息类型常量定义
// 定义了客户端与服务端之间通信的各种消息类型标识符
const (
	WSMsgTypePing                   = "PING"                      // 心跳检测请求消息类型
	WSMsgTypePong                   = "PONG"                      // 心跳检测响应消息类型
	WSMsgTypeChatStream             = "CHAT_STREAM"               // 聊天流消息类型，用于传输连续的聊天数据
	WSMsgTypeError                  = "ERROR"                     // 错误消息类型，用于传输错误信息
	WSMsgTypeCmdSyncInitState       = "CMD_SYNC_INIT_STATE"       // 同步初始状态命令消息类型
	WSMsgTypeCmdUserInput           = "CMD_USER_INPUT"            // 用户输入命令消息类型
	WSMsgTypeEvtInitState           = "EVT_INIT_STATE"            // 初始化状态事件消息类型
	WSMsgTypeReqGetCalendarMetadata = "REQ_GET_CALENDAR_METADATA" // 获取日历元数据请求消息类型
	WSMsgTypeResCalendarMetadata    = "RES_CALENDAR_METADATA"     // 日历元数据响应消息类型
	WSMsgTypeReqGetChatHistory      = "REQ_GET_CHAT_HISTORY"      // 获取聊天历史请求消息类型
	WSMsgTypeResChatHistory         = "RES_CHAT_HISTORY"          // 聊天历史响应消息类型
	// WSMsgTypeEvtMemorySync 长期记忆同步事件消息类型
	// Phase 6 新增：通知前端长期记忆已更新，触发 UI 刷新记忆面板
	WSMsgTypeEvtMemorySync = "EVT_MEMORY_SYNC"
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
