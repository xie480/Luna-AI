package repository

import (
	"context"
	"fmt"

	"gorm.io/gorm"
	"luna-ai/backend/runtime/internal/infrastructure"
)

// PromptPGRepo 提供对 prompt_templates 和 prompt_versions 表的访问
type PromptPGRepo struct {
	db *gorm.DB
}

// NewPromptPGRepo 创建 PromptPGRepo
func NewPromptPGRepo(client *infrastructure.PostgresClient) *PromptPGRepo {
	return &PromptPGRepo{
		db: client.GetDB(),
	}
}

// ListTemplates 获取所有模板列表
func (r *PromptPGRepo) ListTemplates(ctx context.Context) ([]PromptTemplate, error) {
	var templates []PromptTemplate
	if err := r.db.WithContext(ctx).Find(&templates).Error; err != nil {
		return nil, fmt.Errorf("获取模板列表失败: %w", err)
	}
	return templates, nil
}

// GetTemplate 获取模板
func (r *PromptPGRepo) GetTemplate(ctx context.Context, id string) (*PromptTemplate, error) {
	var template PromptTemplate
	if err := r.db.WithContext(ctx).First(&template, "id = ?", id).Error; err != nil {
		return nil, fmt.Errorf("获取模板失败: %w", err)
	}
	return &template, nil
}

// GetTemplateByName 获取模板
func (r *PromptPGRepo) GetTemplateByName(ctx context.Context, name string) (*PromptTemplate, error) {
	var template PromptTemplate
	if err := r.db.WithContext(ctx).First(&template, "name = ?", name).Error; err != nil {
		return nil, fmt.Errorf("获取模板失败: %w", err)
	}
	return &template, nil
}

// GetTemplatesByCategory 获取指定分类的模板
func (r *PromptPGRepo) GetTemplatesByCategory(ctx context.Context, category string) ([]PromptTemplate, error) {
	var templates []PromptTemplate
	if err := r.db.WithContext(ctx).Where("category = ?", category).Find(&templates).Error; err != nil {
		return nil, fmt.Errorf("获取分类模板失败: %w", err)
	}
	return templates, nil
}

// CreateTemplate 创建模板
func (r *PromptPGRepo) CreateTemplate(ctx context.Context, template *PromptTemplate) error {
	if err := r.db.WithContext(ctx).Create(template).Error; err != nil {
		return fmt.Errorf("创建模板失败: %w", err)
	}
	return nil
}

// UpdateTemplate 更新模板
func (r *PromptPGRepo) UpdateTemplate(ctx context.Context, template *PromptTemplate) error {
	if err := r.db.WithContext(ctx).Save(template).Error; err != nil {
		return fmt.Errorf("更新模板失败: %w", err)
	}
	return nil
}

// GetVersion 获取版本
func (r *PromptPGRepo) GetVersion(ctx context.Context, id string) (*PromptVersion, error) {
	var version PromptVersion
	if err := r.db.WithContext(ctx).First(&version, "id = ?", id).Error; err != nil {
		return nil, fmt.Errorf("获取版本失败: %w", err)
	}
	return &version, nil
}

// GetVersionsByTemplate 获取模板的所有版本
func (r *PromptPGRepo) GetVersionsByTemplate(ctx context.Context, templateID string) ([]PromptVersion, error) {
	var versions []PromptVersion
	if err := r.db.WithContext(ctx).Where("template_id = ?", templateID).Order("version_num desc").Find(&versions).Error; err != nil {
		return nil, fmt.Errorf("获取模板版本失败: %w", err)
	}
	return versions, nil
}

// CreateVersion 创建版本
func (r *PromptPGRepo) CreateVersion(ctx context.Context, version *PromptVersion) error {
	if err := r.db.WithContext(ctx).Create(version).Error; err != nil {
		return fmt.Errorf("创建版本失败: %w", err)
	}
	return nil
}

// UpdateVersion 更新版本
func (r *PromptPGRepo) UpdateVersion(ctx context.Context, version *PromptVersion) error {
	if err := r.db.WithContext(ctx).Save(version).Error; err != nil {
		return fmt.Errorf("更新版本失败: %w", err)
	}
	return nil
}

// DeleteVersion 删除版本
func (r *PromptPGRepo) DeleteVersion(ctx context.Context, id string) error {
	if err := r.db.WithContext(ctx).Delete(&PromptVersion{}, "id = ?", id).Error; err != nil {
		return fmt.Errorf("删除版本失败: %w", err)
	}
	return nil
}

// RunInTransaction 在事务中执行操作
func (r *PromptPGRepo) RunInTransaction(ctx context.Context, fn func(txRepo interface{}) error) error {
	return r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		txRepo := &PromptPGRepo{db: tx}
		return fn(txRepo)
	})
}
