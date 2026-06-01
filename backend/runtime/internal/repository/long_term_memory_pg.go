package repository

import (
	"context"
	"fmt"
	"time"

	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
	"gorm.io/gorm"
)

// LongTermMemoryPGRepo 封装 PostgreSQL 中长期记忆的读写操作
// 做什么：提供长期记忆记录的增删改查，支持按 session_id 查询、软删除和分页检索
// 为什么这样做：PostgreSQL 是长期记忆的 Single Source of Truth，所有记忆写入必须经过事务控制
type LongTermMemoryPGRepo struct {
	db *gorm.DB
}

// NewLongTermMemoryPGRepo 创建 LongTermMemoryPGRepo 实例
func NewLongTermMemoryPGRepo(pg *infrastructure.PostgresClient) *LongTermMemoryPGRepo {
	return &LongTermMemoryPGRepo{db: pg.GetDB()}
}

// NewLongTermMemoryPGRepoWithDB 用于测试，直接注入 gorm.DB
func NewLongTermMemoryPGRepoWithDB(db *gorm.DB) *LongTermMemoryPGRepo {
	return &LongTermMemoryPGRepo{db: db}
}

// Save 保存一条长期记忆记录
// 输入：
//   - ctx: 上下文
//   - memory: *LongTermMemory 长期记忆实体
//
// 输出：error
// 边界条件：
//   - memory.ID 必须非空（由雪花算法生成）
//   - memory.SessionID 必须非空
//   - memory.Status 默认为 MemoryStatusActive
func (r *LongTermMemoryPGRepo) Save(ctx context.Context, memory *LongTermMemory) error {
	if memory.Status == "" {
		memory.Status = MemoryStatusActive
	}
	if err := r.db.WithContext(ctx).Create(memory).Error; err != nil {
		return fmt.Errorf("保存长期记忆记录失败 [session_id=%s]: %w", memory.SessionID, err)
	}
	logger.Info(ctx, "长期记忆记录已保存", "session_id", memory.SessionID, "id", memory.ID)
	return nil
}

// GetBySessionID 根据会话 ID 获取长期记忆记录
// 输入：
//   - ctx: 上下文
//   - sessionID: 会话 ID（自然日格式 YYYYMMDD）
//
// 输出：*LongTermMemory, error（未找到时返回 nil, nil）
func (r *LongTermMemoryPGRepo) GetBySessionID(ctx context.Context, sessionID string) (*LongTermMemory, error) {
	var memory LongTermMemory
	err := r.db.WithContext(ctx).
		Where("session_id = ? AND status = ?", sessionID, MemoryStatusActive).
		First(&memory).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, nil
		}
		return nil, fmt.Errorf("查询长期记忆记录失败 [session_id=%s]: %w", sessionID, err)
	}
	return &memory, nil
}

// GetByIDs 根据 ID 列表批量获取长期记忆记录
// 输入：
//   - ctx: 上下文
//   - ids: 记忆 ID 列表
//
// 输出：[]LongTermMemory, error
// 边界条件：仅返回 status=MemoryStatusActive 的记录
func (r *LongTermMemoryPGRepo) GetByIDs(ctx context.Context, ids []string) ([]LongTermMemory, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	var memories []LongTermMemory
	err := r.db.WithContext(ctx).
		Where("id IN ? AND status = ?", ids, MemoryStatusActive).
		Find(&memories).Error
	if err != nil {
		return nil, fmt.Errorf("批量查询长期记忆记录失败: %w", err)
	}
	return memories, nil
}

// SoftDelete 软删除指定的长期记忆记录
// 输入：
//   - ctx: 上下文
//   - id: 记忆 ID
//
// 输出：error
func (r *LongTermMemoryPGRepo) SoftDelete(ctx context.Context, id string) error {
	err := r.db.WithContext(ctx).
		Model(&LongTermMemory{}).
		Where("id = ?", id).
		Update("status", MemoryStatusDeleted).
		Error
	if err != nil {
		return fmt.Errorf("软删除长期记忆记录失败 [id=%s]: %w", id, err)
	}
	logger.Info(ctx, "长期记忆记录已软删除", "id", id)
	return nil
}

// ListByMonth 按月查询长期记忆记录列表
// 输入：
//   - ctx: 上下文
//   - yearMonth: 年月（YYYY-MM）
//
// 输出：[]LongTermMemory, error
// 用例：前端日历面板按月加载历史记忆概览
func (r *LongTermMemoryPGRepo) ListByMonth(ctx context.Context, yearMonth string) ([]LongTermMemory, error) {
	loc := time.Local
	start, err := time.ParseInLocation("2006-01-02 15:04:05", fmt.Sprintf("%s-01 00:00:00", yearMonth), loc)
	if err != nil {
		return nil, fmt.Errorf("解析月份时间失败: %w", err)
	}
	end := start.AddDate(0, 1, 0)

	var memories []LongTermMemory
	err = r.db.WithContext(ctx).
		Where("created_at >= ? AND created_at < ? AND status = ?", start, end, MemoryStatusActive).
		Order("created_at DESC").
		Find(&memories).Error
	if err != nil {
		return nil, fmt.Errorf("按月查询长期记忆记录失败: %w", err)
	}
	return memories, nil
}

// GetAllActiveSessionIDs 获取所有活跃的长期记忆会话 ID 列表
// 输入：
//   - ctx: 上下文
//
// 输出：[]string, error
// 用途：启动时兜底检测用，判断哪些历史会话已有长期记忆记录
func (r *LongTermMemoryPGRepo) GetAllActiveSessionIDs(ctx context.Context) ([]string, error) {
	var sessionIDs []string
	err := r.db.WithContext(ctx).
		Model(&LongTermMemory{}).
		Where("status = ?", MemoryStatusActive).
		Pluck("session_id", &sessionIDs).Error
	if err != nil {
		return nil, fmt.Errorf("查询所有活跃会话 ID 失败: %w", err)
	}
	return sessionIDs, nil
}

// DeleteBySessionID 删除指定会话的所有长期记忆记录
// 输入：
//   - ctx: 上下文
//   - sessionID: 会话 ID
//
// 输出：error
// 用途：记忆撤销或重置时清理指定会话的记忆
func (r *LongTermMemoryPGRepo) DeleteBySessionID(ctx context.Context, sessionID string) error {
	err := r.db.WithContext(ctx).
		Where("session_id = ?", sessionID).
		Delete(&LongTermMemory{}).Error
	if err != nil {
		return fmt.Errorf("删除会话长期记忆记录失败 [session_id=%s]: %w", sessionID, err)
	}
	logger.Info(ctx, "会话长期记忆记录已删除", "session_id", sessionID)
	return nil
}
