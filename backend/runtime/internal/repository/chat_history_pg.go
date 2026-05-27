package repository

import (
	"context"
	"fmt"

	"luna-ai/backend/runtime/internal/infrastructure"
	"gorm.io/gorm"
)

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

// SaveInteraction 保存单次问答交互记录（一问一答绑定为完整存储单元）到 PostgreSQL
func (r *ChatHistoryPGRepo) SaveInteraction(ctx context.Context, interaction *InteractionModel) error {
	if err := r.db.WithContext(ctx).Create(interaction).Error; err != nil {
		return fmt.Errorf("保存 Interaction 到 PostgreSQL 失败: %w", err)
	}
	return nil
}

// GetInteractionsBySessionID 分页查询历史交互记录
func (r *ChatHistoryPGRepo) GetInteractionsBySessionID(ctx context.Context, sessionID string, limit int, offset int) ([]InteractionModel, error) {
	var interactions []InteractionModel
	err := r.db.WithContext(ctx).
		Where("session_id = ?", sessionID).
		Order("created_at DESC").
		Limit(limit).
		Offset(offset).
		Find(&interactions).Error

	if err != nil {
		return nil, fmt.Errorf("从 PostgreSQL 查询历史交互记录失败: %w", err)
	}
	return interactions, nil
}
