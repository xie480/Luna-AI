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

// GetInteractionsByDate 查询指定日期的所有交互记录
// 做什么：根据传入的日期（YYYY-MM-DD），查询该日 00:00:00 至 23:59:59 的所有记录，按时间升序排列
// 为什么这样做：为前端聊天记录展示区提供详细的持久化数据
// 输入输出：
//   - 输入：date (YYYY-MM-DD)
//   - 输出：[]InteractionModel, error
func (r *ChatHistoryPGRepo) GetInteractionsByDate(ctx context.Context, date string) ([]InteractionModel, error) {
	var interactions []InteractionModel
	
	// 构建当天的起止时间字符串
	startTime := fmt.Sprintf("%s 00:00:00", date)
	endTime := fmt.Sprintf("%s 23:59:59", date)

	err := r.db.WithContext(ctx).
		Where("created_at >= ? AND created_at <= ?", startTime, endTime).
		Order("created_at ASC").
		Find(&interactions).Error

	if err != nil {
		return nil, fmt.Errorf("从 PostgreSQL 查询指定日期交互记录失败: %w", err)
	}
	return interactions, nil
}

// GetActiveDatesByMonth 聚合查询指定月份中有交互记录的日期列表
// 做什么：查询指定月份（YYYY-MM）内，存在交互记录的所有不重复的日期（DD）
// 为什么这样做：当 Redis 缓存未命中时，从 PG 重建日历元数据
// 输入输出：
//   - 输入：yearMonth (YYYY-MM)
//   - 输出：[]string (日期列表，如 ["01", "15"]), error
func (r *ChatHistoryPGRepo) GetActiveDatesByMonth(ctx context.Context, yearMonth string) ([]string, error) {
	var dates []string
	
	// 构建当月的起止时间字符串
	// 使用 PostgreSQL 的日期函数来处理月份的最后一天，避免 31 号在某些月份报错
	startTime := fmt.Sprintf("%s-01 00:00:00", yearMonth)
	
	// 使用 GORM 的 Pluck 查询格式化后的日期
	// 注意：这里使用了 PostgreSQL 特有的 TO_CHAR 函数。如果需要兼容 SQLite，可能需要调整。
	// 考虑到 agent.md 中明确主存储为 PostgreSQL 15+，这里直接使用 PG 语法。
	err := r.db.WithContext(ctx).
		Model(&InteractionModel{}).
		Select("DISTINCT TO_CHAR(created_at, 'DD')").
		Where("created_at >= ?::timestamp AND created_at < (?::timestamp + interval '1 month')", startTime, startTime).
		Pluck("TO_CHAR(created_at, 'DD')", &dates).Error

	if err != nil {
		return nil, fmt.Errorf("从 PostgreSQL 聚合查询活跃日期失败: %w", err)
	}
	return dates, nil
}
