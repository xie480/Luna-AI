package repository

import (
	"time"
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

// SystemConfig 对应 PostgreSQL 中的 system_config 表（动态配置）
type SystemConfig struct {
	ID          string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	Key         string    `gorm:"column:key;type:varchar(255);not null;uniqueIndex"`
	Value       string    `gorm:"column:value;type:text;not null"`
	IsEncrypted bool      `gorm:"column:is_encrypted;type:boolean;not null;default:false"`
	Description string    `gorm:"column:description;type:text"`
	CreatedAt   time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP"`
	UpdatedAt   time.Time `gorm:"column:updated_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP"`
}

// TableName 指定表名
func (SystemConfig) TableName() string {
	return "system_config"
}

// PromptTemplate 对应 PostgreSQL 中的 prompt_templates 表（提示词模板元数据）
type PromptTemplate struct {
	ID              string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	Name            string    `gorm:"column:name;type:varchar(255);not null;uniqueIndex"`
	Category        string    `gorm:"column:category;type:varchar(100);not null;index:idx_prompt_templates_category_slot"`
	SlotPosition    string    `gorm:"column:slot_position;type:varchar(50);not null;index:idx_prompt_templates_category_slot"`
	IsSystem        bool      `gorm:"column:is_system;type:boolean;not null;default:false"`
	ActiveVersionID string    `gorm:"column:active_version_id;type:varchar(64)"`
	CreatedAt       time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP"`
	UpdatedAt       time.Time `gorm:"column:updated_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP"`
}

// TableName 指定表名
func (PromptTemplate) TableName() string {
	return "prompt_templates"
}

// PromptVersion 对应 PostgreSQL 中的 prompt_versions 表（提示词模板具体版本内容）
type PromptVersion struct {
	ID         string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	TemplateID string    `gorm:"column:template_id;type:varchar(64);not null;index"`
	VersionNum int       `gorm:"column:version_num;type:integer;not null"`
	Content    string    `gorm:"column:content;type:text;not null"`
	Variables  string    `gorm:"column:variables;type:jsonb;not null;default:'[]'"` // JSON array of strings
	Status     string    `gorm:"column:status;type:varchar(50);not null"`           // draft, published, archived
	CreatedAt  time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP"`
}

// TableName 指定表名
func (PromptVersion) TableName() string {
	return "prompt_versions"
}
