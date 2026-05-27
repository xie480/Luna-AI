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
