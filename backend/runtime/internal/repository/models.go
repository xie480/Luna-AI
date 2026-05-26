package repository

import (
	"time"
)

// ChatMessageModel 对应 PostgreSQL 中的 chat_messages 表
type ChatMessageModel struct {
	ID        string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	SessionID string    `gorm:"column:session_id;type:varchar(64);not null;index:idx_chat_messages_session_id_created_at"`
	MsgID     string    `gorm:"column:msg_id;type:varchar(64);not null;unique"`
	Role      string    `gorm:"column:role;type:varchar(20);not null"`
	Content   string    `gorm:"column:content;type:text;not null"`
	CreatedAt time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP;index:idx_chat_messages_session_id_created_at,sort:desc"`
}

// TableName 指定表名
func (ChatMessageModel) TableName() string {
	return "chat_messages"
}
