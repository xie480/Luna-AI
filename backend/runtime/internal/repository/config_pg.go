package repository

import (
	"context"
	"fmt"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"luna-ai/backend/runtime/internal/infrastructure"
)

// ConfigPGRepo 提供对 system_config 表的访问
type ConfigPGRepo struct {
	db *gorm.DB
}

// NewConfigPGRepo 创建 ConfigPGRepo
func NewConfigPGRepo(client *infrastructure.PostgresClient) *ConfigPGRepo {
	return &ConfigPGRepo{
		db: client.GetDB(),
	}
}

// GetAll 获取所有配置
func (r *ConfigPGRepo) GetAll(ctx context.Context) ([]SystemConfig, error) {
	var configs []SystemConfig
	if err := r.db.WithContext(ctx).Find(&configs).Error; err != nil {
		return nil, fmt.Errorf("获取所有配置失败: %w", err)
	}
	return configs, nil
}

// Save 保存或更新配置 (Upsert)
func (r *ConfigPGRepo) Save(ctx context.Context, config *SystemConfig) error {
	// 使用 OnConflict 实现 Upsert
	if err := r.db.WithContext(ctx).Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "key"}},
		DoUpdates: clause.AssignmentColumns([]string{"value", "is_encrypted", "updated_at"}),
	}).Create(config).Error; err != nil {
		return fmt.Errorf("保存配置失败: %w", err)
	}
	return nil
}
