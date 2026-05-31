package repository

import (
	"context"
	"fmt"
	"time"

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
	
	// 解析本地时间的起止时间，避免数据库时区与本地时区不一致导致查询遗漏
	loc := time.Local
	start, err := time.ParseInLocation("2006-01-02 15:04:05", fmt.Sprintf("%s 00:00:00", date), loc)
	if err != nil {
		return nil, fmt.Errorf("解析开始时间失败: %w", err)
	}
	end, err := time.ParseInLocation("2006-01-02 15:04:05", fmt.Sprintf("%s 23:59:59", date), loc)
	if err != nil {
		return nil, fmt.Errorf("解析结束时间失败: %w", err)
	}

	err = r.db.WithContext(ctx).
		Where("created_at >= ? AND created_at <= ?", start, end).
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
	
	// 解析本地时间的当月1号
	loc := time.Local
	start, err := time.ParseInLocation("2006-01-02 15:04:05", fmt.Sprintf("%s-01 00:00:00", yearMonth), loc)
	if err != nil {
		return nil, fmt.Errorf("解析月份时间失败: %w", err)
	}
	// 计算下个月1号
	end := start.AddDate(0, 1, 0)

	// 提取该月所有的 created_at 时间戳
	var createdAts []time.Time
	err = r.db.WithContext(ctx).
		Model(&InteractionModel{}).
		Select("created_at").
		Where("created_at >= ? AND created_at < ?", start, end).
		Pluck("created_at", &createdAts).Error

	if err != nil {
		return nil, fmt.Errorf("从 PostgreSQL 聚合查询活跃日期失败: %w", err)
	}

	// 在 Go 层面转换为本地时间并提取日期，彻底避免数据库时区函数带来的偏差
	dateMap := make(map[string]bool)
	for _, t := range createdAts {
		dateMap[t.In(loc).Format("02")] = true
	}

	for d := range dateMap {
		dates = append(dates, d)
	}

	return dates, nil
}
