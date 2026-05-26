package repository

import (
	"context"
	"fmt"

	"luna-ai/backend/runtime/internal/infrastructure"
)

import "gorm.io/gorm"

// ChatHistoryPGRepo 封装 PostgreSQL 长期归档读写
type ChatHistoryPGRepo struct {
	db *gorm.DB
}

// NewChatHistoryPGRepo 创建 ChatHistoryPGRepo 实例
func NewChatHistoryPGRepo(pg *infrastructure.PostgresClient) *ChatHistoryPGRepo {
	return &ChatHistoryPGRepo{db: pg.GetDB()}
}

// NewChatHistoryPGRepoWithDB 用于测试，直接注入 gorm.DB
func NewChatHistoryPGRepoWithDB(db *gorm.DB) *ChatHistoryPGRepo {
	return &ChatHistoryPGRepo{db: db}
}

// SaveMessage 保存单条消息到 PostgreSQL
func (r *ChatHistoryPGRepo) SaveMessage(ctx context.Context, msg *ChatMessageModel) error {
	if err := r.db.WithContext(ctx).Create(msg).Error; err != nil {
		return fmt.Errorf("保存消息到 PostgreSQL 失败: %w", err)
	}
	return nil
}

// GetMessagesBySessionID 分页查询历史消息
func (r *ChatHistoryPGRepo) GetMessagesBySessionID(ctx context.Context, sessionID string, limit int, offset int) ([]ChatMessageModel, error) {
	var messages []ChatMessageModel
	err := r.db.WithContext(ctx).
		Where("session_id = ?", sessionID).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&messages).Error

	if err != nil {
		return nil, fmt.Errorf("从 PostgreSQL 查询历史消息失败: %w", err)
	}
	return messages, nil
}
