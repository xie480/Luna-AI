package repository

import (
	"time"
)

// MemoryStatus 定义长期记忆状态枚举
type MemoryStatus string

const (
	// MemoryStatusActive 生效中
	MemoryStatusActive MemoryStatus = "ACTIVE"
	// MemoryStatusDeleted 软删除
	MemoryStatusDeleted MemoryStatus = "DELETED"
)

// InteractionModel 对应 PostgreSQL 中的 interactions 表（问答聚合）
// 将用户的一问与系统的一答严格绑定为一个完整的存储单元
type InteractionModel struct {
	ID               string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	SessionID        string    `gorm:"column:session_id;type:varchar(64);not null;index:idx_interactions_session_id_created_at"`
	MessageID        string    `gorm:"column:message_id;type:varchar(64);not null;unique"`
	UserContent      string    `gorm:"column:user_content;type:text;not null"`
	AssistantContent string    `gorm:"column:assistant_content;type:text;not null"`
	// Thought 字段存储助手消息的内心独白（thought），用于记忆系统展示历史心理状态
	Thought   string    `gorm:"column:thought;type:text;not null;default:''"`
	Emotion   string    `gorm:"column:emotion;type:varchar(50);not null;default:''"`
	Error     string    `gorm:"column:error;type:text;not null;default:''"`
	CreatedAt time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP;index:idx_interactions_session_id_created_at,sort:desc"`
}

// TableName 指定表名
func (InteractionModel) TableName() string {
	return "interactions"
}

// PromptTemplate 对应 PostgreSQL 中的 prompt_templates 表（提示词模板元数据）
type PromptTemplate struct {
	ID              string    `gorm:"column:id;primaryKey;type:varchar(64)" json:"id"`
	Name            string    `gorm:"column:name;type:varchar(255);not null;uniqueIndex" json:"name"`
	Category        string    `gorm:"column:category;type:varchar(100);not null;index:idx_prompt_templates_category_slot" json:"category"`
	SlotPosition    string    `gorm:"column:slot_position;type:varchar(50);not null;index:idx_prompt_templates_category_slot" json:"slot_position"`
	IsSystem        bool      `gorm:"column:is_system;type:boolean;not null;default:false" json:"is_system"`
	ActiveVersionID string    `gorm:"column:active_version_id;type:varchar(64)" json:"active_version_id"`
	CreatedAt       time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"created_at"`
	UpdatedAt       time.Time `gorm:"column:updated_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"updated_at"`
}

// TableName 指定表名
func (PromptTemplate) TableName() string {
	return "prompt_templates"
}

// PromptVersion 对应 PostgreSQL 中的 prompt_versions 表（提示词模板具体版本内容）
type PromptVersion struct {
	ID         string    `gorm:"column:id;primaryKey;type:varchar(64)" json:"id"`
	TemplateID string    `gorm:"column:template_id;type:varchar(64);not null;index" json:"template_id"`
	VersionNum int       `gorm:"column:version_num;type:integer;not null" json:"version_num"`
	Content    string    `gorm:"column:content;type:text;not null" json:"content"`
	Variables  string    `gorm:"column:variables;type:jsonb;not null;default:'[]'" json:"variables"` // JSON array of strings
	Status     string    `gorm:"column:status;type:varchar(50);not null" json:"status"`           // draft, published, archived
	CreatedAt  time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"created_at"`
}

// TableName 指定表名
func (PromptVersion) TableName() string {
	return "prompt_versions"
}

// LongTermMemory 对应 PostgreSQL 中的 long_term_memories 表（长期记忆）
// 做什么：存储每日会话的深度压缩摘要，作为长期记忆的 Single Source of Truth
type LongTermMemory struct {
	ID        string       `gorm:"column:id;primaryKey;type:varchar(64)" json:"id"`
	SessionID string       `gorm:"column:session_id;type:varchar(64);not null;index:idx_ltm_session_id" json:"session_id"`
	Summary   string       `gorm:"column:summary;type:text;not null" json:"summary"`
	Status    MemoryStatus `gorm:"column:status;type:varchar(20);not null;default:'ACTIVE'" json:"status"`
	CreatedAt time.Time    `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"created_at"`
	UpdatedAt time.Time    `gorm:"column:updated_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"updated_at"`
}

// TableName 指定表名
func (LongTermMemory) TableName() string {
	return "long_term_memories"
}

// ApiConfigPreset 对应 PostgreSQL 中的 api_config_presets 表（API 配置预设）
type ApiConfigPreset struct {
	ID                string    `gorm:"column:id;primaryKey;type:varchar(64)" json:"id"`
	Name              string    `gorm:"column:name;type:varchar(255);not null;uniqueIndex" json:"name"`
	IsActive          bool      `gorm:"column:is_active;type:boolean;not null;default:false" json:"is_active"`
	LargeModelConfig  string    `gorm:"column:large_model_config;type:jsonb;not null" json:"large_model_config"`
	MediumModelConfig string    `gorm:"column:medium_model_config;type:jsonb;not null" json:"medium_model_config"`
	SmallModelConfig  string    `gorm:"column:small_model_config;type:jsonb;not null" json:"small_model_config"`
	CreatedAt         time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"created_at"`
	UpdatedAt         time.Time `gorm:"column:updated_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP" json:"updated_at"`
}

// TableName 指定表名
func (ApiConfigPreset) TableName() string {
	return "api_config_presets"
}
