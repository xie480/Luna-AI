package repository

import (
	"context"
	"fmt"

	"gorm.io/gorm"
	"luna-ai/backend/runtime/internal/infrastructure"
)

// ConfigPresetPGRepo 提供对 api_config_presets 表的访问
type ConfigPresetPGRepo struct {
	db *gorm.DB
}

// NewConfigPresetPGRepo 创建 ConfigPresetPGRepo
func NewConfigPresetPGRepo(client *infrastructure.PostgresClient) *ConfigPresetPGRepo {
	return &ConfigPresetPGRepo{
		db: client.GetDB(),
	}
}

// GetAll 获取所有预设
func (r *ConfigPresetPGRepo) GetAll(ctx context.Context) ([]ApiConfigPreset, error) {
	var presets []ApiConfigPreset
	if err := r.db.WithContext(ctx).Order("created_at DESC").Find(&presets).Error; err != nil {
		return nil, fmt.Errorf("获取所有预设失败: %w", err)
	}
	return presets, nil
}

// GetByID 根据 ID 获取预设
func (r *ConfigPresetPGRepo) GetByID(ctx context.Context, id string) (*ApiConfigPreset, error) {
	var preset ApiConfigPreset
	if err := r.db.WithContext(ctx).Where("id = ?", id).First(&preset).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, nil
		}
		return nil, fmt.Errorf("获取预设失败: %w", err)
	}
	return &preset, nil
}

// GetActive 获取当前激活的预设
func (r *ConfigPresetPGRepo) GetActive(ctx context.Context) (*ApiConfigPreset, error) {
	var preset ApiConfigPreset
	if err := r.db.WithContext(ctx).Where("is_active = ?", true).First(&preset).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return nil, nil
		}
		return nil, fmt.Errorf("获取激活预设失败: %w", err)
	}
	return &preset, nil
}

// Save 保存或更新预设
func (r *ConfigPresetPGRepo) Save(ctx context.Context, preset *ApiConfigPreset) error {
	if err := r.db.WithContext(ctx).Save(preset).Error; err != nil {
		return fmt.Errorf("保存预设失败: %w", err)
	}
	return nil
}

// Delete 删除预设
func (r *ConfigPresetPGRepo) Delete(ctx context.Context, id string) error {
	if err := r.db.WithContext(ctx).Where("id = ?", id).Delete(&ApiConfigPreset{}).Error; err != nil {
		return fmt.Errorf("删除预设失败: %w", err)
	}
	return nil
}

// SetActive 设置激活的预设，并将其他预设设为非激活
func (r *ConfigPresetPGRepo) SetActive(ctx context.Context, id string) error {
	return r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		// 1. 将所有预设设为非激活
		if err := tx.Model(&ApiConfigPreset{}).Where("1 = 1").Update("is_active", false).Error; err != nil {
			return fmt.Errorf("重置激活状态失败: %w", err)
		}

		// 2. 将指定预设设为激活
		if err := tx.Model(&ApiConfigPreset{}).Where("id = ?", id).Update("is_active", true).Error; err != nil {
			return fmt.Errorf("设置激活状态失败: %w", err)
		}

		return nil
	})
}
