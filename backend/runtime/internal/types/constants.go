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

// PrimaryIntent 核心意图标识
type PrimaryIntent string

const (
	IntentModifyPlan     PrimaryIntent = "MODIFY_PLAN"     // 修改计划
	IntentGreeting       PrimaryIntent = "GREETING"        // 日常问候
	IntentQueryInfo      PrimaryIntent = "QUERY_INFO"      // 信息查询
	IntentEmotionVenting PrimaryIntent = "EMOTION_VENTING" // 情绪宣泄
	IntentSystemCommand  PrimaryIntent = "SYSTEM_COMMAND"  // 系统指令
	IntentToolInvocation PrimaryIntent = "TOOL_INVOCATION" // 明确的工具调用
)

// ValidPrimaryIntents 返回所有合法的 PrimaryIntent 值
func ValidPrimaryIntents() []string {
	return []string{
		string(IntentModifyPlan),
		string(IntentGreeting),
		string(IntentQueryInfo),
		string(IntentEmotionVenting),
		string(IntentSystemCommand),
		string(IntentToolInvocation),
	}
}

// IntentCategory 意图大类
type IntentCategory string

const (
	CategoryTaskManagement IntentCategory = "TASK_MANAGEMENT" // 任务管理类
	CategoryChat           IntentCategory = "CHAT"            // 闲聊陪伴类
	CategoryKnowledgeQuery IntentCategory = "KNOWLEDGE_QUERY" // 知识问答类
	CategoryEmotionSupport IntentCategory = "EMOTION_SUPPORT" // 情感支持类
)

// ValidIntentCategories 返回所有合法的 IntentCategory 值
func ValidIntentCategories() []string {
	return []string{
		string(CategoryTaskManagement),
		string(CategoryChat),
		string(CategoryKnowledgeQuery),
		string(CategoryEmotionSupport),
	}
}

// DagRouteHint DAG路由暗示
type DagRouteHint string

const (
	RouteMultiSourceRetrieval DagRouteHint = "MULTI_SOURCE_RETRIEVAL_WORKFLOW" // 多源检索工作流
	RouteFastChat             DagRouteHint = "FAST_CHAT"                       // 快速闲聊通道
	RouteAgenticWorkflow      DagRouteHint = "AGENTIC_WORKFLOW"                // 复杂Agent规划流
	RouteGatingApproval       DagRouteHint = "GATING_APPROVAL"                 // 强制人工审批流
)

// ValidDagRouteHints 返回所有合法的 DagRouteHint 值
func ValidDagRouteHints() []string {
	return []string{
		string(RouteMultiSourceRetrieval),
		string(RouteFastChat),
		string(RouteAgenticWorkflow),
		string(RouteGatingApproval),
	}
}

// RetrievalType 检索类型
type RetrievalType string

const (
	RetrievalLongTermMemory      RetrievalType = "LONG_TERM_MEMORY"      // 长期记忆
	RetrievalExternalKnowledge   RetrievalType = "EXTERNAL_KNOWLEDGE"    // 外部知识
	RetrievalExperienceReflection RetrievalType = "EXPERIENCE_REFLECTION" // 经验教训
)

// ValidRetrievalTypes 返回所有合法的 RetrievalType 值
func ValidRetrievalTypes() []string {
	return []string{
		string(RetrievalLongTermMemory),
		string(RetrievalExternalKnowledge),
		string(RetrievalExperienceReflection),
	}
}
