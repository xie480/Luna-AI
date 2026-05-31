package prompt

import (
	"context"
	"fmt"
	"strings"

	"go.uber.org/zap"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
)

// PromptRepository 定义 Prompt 仓储接口
type PromptRepository interface {
	ListTemplates(ctx context.Context) ([]repository.PromptTemplate, error)
	GetTemplate(ctx context.Context, id string) (*repository.PromptTemplate, error)
	GetTemplateByName(ctx context.Context, name string) (*repository.PromptTemplate, error)
	GetTemplatesByCategory(ctx context.Context, category string) ([]repository.PromptTemplate, error)
	CreateTemplate(ctx context.Context, template *repository.PromptTemplate) error
	UpdateTemplate(ctx context.Context, template *repository.PromptTemplate) error
	GetVersion(ctx context.Context, id string) (*repository.PromptVersion, error)
	GetVersionsByTemplate(ctx context.Context, templateID string) ([]repository.PromptVersion, error)
	CreateVersion(ctx context.Context, version *repository.PromptVersion) error
	UpdateVersion(ctx context.Context, version *repository.PromptVersion) error
	DeleteVersion(ctx context.Context, id string) error
	RunInTransaction(ctx context.Context, fn func(txRepo interface{}) error) error
}

// PromptCache 定义 Prompt 缓存接口
type PromptCache interface {
	GetAssembledPrompt(ctx context.Context, category string, variables map[string]string) (string, error)
	InvalidateCache(ctx context.Context, category string) error
}

// Manager 负责 Prompt 模板与版本的管理
type Manager struct {
	repo     PromptRepository
	cacheMgr PromptCache
}

// NewManager 创建 Manager
func NewManager(repo PromptRepository, cacheMgr PromptCache) *Manager {
	return &Manager{
		repo:     repo,
		cacheMgr: cacheMgr,
	}
}

// AssemblePrompt 根据业务分类组装完整的 Prompt 字符串
// 输入：
//   - ctx: 上下文
//   - category: 业务分类（如 "chat" / "summary"）
//   - variables: 模板变量键值对
//
// 输出：
//   - 组装后的完整 prompt 字符串（即使 db 和 redis 都不可用也返回一个基本提示文本）
//   - 错误信息
func (m *Manager) AssemblePrompt(ctx context.Context, category string, variables map[string]string) (string, error) {
	// 通过缓存层获取并将各 slot 注入占位符
	prompt, err := m.cacheMgr.GetAssembledPrompt(ctx, category, variables)
	if err != nil {
		logger.Warn(ctx, "获取组装 Prompt 失败", zap.String("category", category), zap.Error(err))
		// 返回一个最基本的安全兜底文本，避免系统完全不可用
		return buildMinimalPrompt(variables), nil
	}

	// 清理剩余未被注入的占位符
	prompt = strings.ReplaceAll(prompt, PlaceholderSystem, "")
	prompt = strings.ReplaceAll(prompt, PlaceholderMemory, "")
	prompt = strings.ReplaceAll(prompt, PlaceholderRuntime, "")

	// 去除多余空行（清理因占位符移除而产生的连续空行）
	prompt = cleanEmptyLines(prompt)

	logger.Info(ctx, "组装 Prompt 成功",
		zap.String("category", category),
		zap.Int("prompt_length", len(prompt)))

	return prompt, nil
}

// buildMinimalPrompt 构建最基本的安全兜底提示文本
func buildMinimalPrompt(variables map[string]string) string {
	var b strings.Builder
	b.WriteString("你是一个 AI 助手。\n\n")
	b.WriteString("当前时间：")
	b.WriteString(variables["CURRENT_TIME"])
	b.WriteString("\n\n用户输入：")
	b.WriteString(variables["CURRENT_MESSAGE"])
	return b.String()
}

// cleanEmptyLines 清理连续多余的空行（3行以上压缩为2行）
func cleanEmptyLines(input string) string {
	for strings.Contains(input, "\n\n\n") {
		input = strings.ReplaceAll(input, "\n\n\n", "\n\n")
	}
	return strings.TrimSpace(input)
}

// ListTemplates 获取所有模板列表
func (m *Manager) ListTemplates(ctx context.Context) ([]repository.PromptTemplate, error) {
	return m.repo.ListTemplates(ctx)
}

// GetVersions 获取指定模板的所有版本
func (m *Manager) GetVersions(ctx context.Context, templateID string) ([]repository.PromptVersion, error) {
	return m.repo.GetVersionsByTemplate(ctx, templateID)
}

// CreateTemplate 创建新的 Prompt 模板
func (m *Manager) CreateTemplate(ctx context.Context, name, category, slotPosition string, isSystem bool) (*repository.PromptTemplate, error) {
	tmpl := &repository.PromptTemplate{
		ID:           snowflake.GenerateStringID(),
		Name:         name,
		Category:     category,
		SlotPosition: slotPosition,
		IsSystem:     isSystem,
	}

	if err := m.repo.CreateTemplate(ctx, tmpl); err != nil {
		return nil, err
	}

	logger.Info(ctx, "创建 Prompt 模板成功", zap.String("template_id", tmpl.ID), zap.String("name", name))

	return tmpl, nil
}

// CreateVersion 为指定模板创建新版本
func (m *Manager) CreateVersion(ctx context.Context, templateID, content, variables string) (*repository.PromptVersion, error) {
	// 获取当前最大版本号
	versions, err := m.repo.GetVersionsByTemplate(ctx, templateID)
	if err != nil {
		return nil, err
	}

	nextVersionNum := 1
	if len(versions) > 0 {
		nextVersionNum = versions[0].VersionNum + 1
	}

	// 确保 variables 是有效的 JSON 数组字符串
	if variables == "" {
		variables = "[]"
	} else if !strings.HasPrefix(variables, "[") {
		// 如果前端传过来的是逗号分隔的字符串，转换为 JSON 数组
		vars := strings.Split(variables, ",")
		for i, v := range vars {
			vars[i] = fmt.Sprintf(`"%s"`, strings.TrimSpace(v))
		}
		variables = fmt.Sprintf("[%s]", strings.Join(vars, ","))
	}

	version := &repository.PromptVersion{
		ID:         snowflake.GenerateStringID(),
		TemplateID: templateID,
		VersionNum: nextVersionNum,
		Content:    content,
		Variables:  variables,
		Status:     "draft",
	}

	if err := m.repo.CreateVersion(ctx, version); err != nil {
		return nil, err
	}

	logger.Info(ctx, "创建 Prompt 版本成功", zap.String("version_id", version.ID), zap.String("template_id", templateID))

	return version, nil
}

// PublishVersion 发布版本（将其设为模板的 active_version_id）
// 发布成功后自动使对应的 Redis 缓存失效
func (m *Manager) PublishVersion(ctx context.Context, templateID, versionID string) error {
	return m.repo.RunInTransaction(ctx, func(txRepo interface{}) error {
		repo := txRepo.(PromptRepository)
		tmpl, err := repo.GetTemplate(ctx, templateID)
		if err != nil {
			return err
		}

		// 验证版本是否存在
		version, err := repo.GetVersion(ctx, versionID)
		if err != nil {
			return err
		}

		if version.TemplateID != templateID {
			return fmt.Errorf("版本 %s 不属于模板 %s", versionID, templateID)
		}

		// 将之前处于 published 状态的版本更新为 deprecated
		versions, err := repo.GetVersionsByTemplate(ctx, templateID)
		if err != nil {
			return err
		}
		for _, v := range versions {
			if v.Status == "published" && v.ID != versionID {
				v.Status = "deprecated"
				if err := repo.UpdateVersion(ctx, &v); err != nil {
					return err
				}
			}
		}

		// 更新当前版本状态为 published
		version.Status = "published"
		if err := repo.UpdateVersion(ctx, version); err != nil {
			return err
		}

		// 更新模板的 active_version_id
		tmpl.ActiveVersionID = versionID
		if err := repo.UpdateTemplate(ctx, tmpl); err != nil {
			return err
		}

		logger.Info(ctx, "发布 Prompt 版本成功", zap.String("template_id", templateID), zap.String("version_id", versionID))

		// 版本发布后自动使缓存失效，下一次请求会从数据库重新加载
		if m.cacheMgr != nil {
			if cacheErr := m.cacheMgr.InvalidateCache(ctx, tmpl.Category); cacheErr != nil {
				logger.Warn(ctx, "清除 Prompt 缓存失败", zap.String("category", tmpl.Category), zap.Error(cacheErr))
			}
		}

		return nil
	})
}

// RollbackVersion 回滚版本
// 物理删除当前处于 published 状态的最新版本，并将目标回滚版本的状态从 deprecated 恢复为 published
func (m *Manager) RollbackVersion(ctx context.Context, templateID, targetVersionID string) error {
	return m.repo.RunInTransaction(ctx, func(txRepo interface{}) error {
		repo := txRepo.(PromptRepository)
		tmpl, err := repo.GetTemplate(ctx, templateID)
		if err != nil {
			return err
		}

		// 验证目标回滚版本是否存在
		targetVersion, err := repo.GetVersion(ctx, targetVersionID)
		if err != nil {
			return err
		}

		if targetVersion.TemplateID != templateID {
			return fmt.Errorf("版本 %s 不属于模板 %s", targetVersionID, templateID)
		}

		if targetVersion.Status != "deprecated" {
			return fmt.Errorf("只能回滚到已废弃(deprecated)的版本，当前状态: %s", targetVersion.Status)
		}

		// 查找当前处于 published 状态的版本
		var currentPublishedVersion *repository.PromptVersion
		versions, err := repo.GetVersionsByTemplate(ctx, templateID)
		if err != nil {
			return err
		}
		for _, v := range versions {
			if v.Status == "published" {
				currentPublishedVersion = &v
				break
			}
		}

		if currentPublishedVersion == nil {
			return fmt.Errorf("未找到当前已发布的版本")
		}

		// 物理删除当前已发布的版本
		if err := repo.DeleteVersion(ctx, currentPublishedVersion.ID); err != nil {
			return err
		}

		// 将目标回滚版本状态更新为 published
		targetVersion.Status = "published"
		if err := repo.UpdateVersion(ctx, targetVersion); err != nil {
			return err
		}

		// 更新模板的 active_version_id
		tmpl.ActiveVersionID = targetVersionID
		if err := repo.UpdateTemplate(ctx, tmpl); err != nil {
			return err
		}

		logger.Info(ctx, "回滚 Prompt 版本成功", zap.String("template_id", templateID), zap.String("target_version_id", targetVersionID), zap.String("deleted_version_id", currentPublishedVersion.ID))

		// 版本回滚后自动使缓存失效
		if m.cacheMgr != nil {
			if cacheErr := m.cacheMgr.InvalidateCache(ctx, tmpl.Category); cacheErr != nil {
				logger.Warn(ctx, "清除 Prompt 缓存失败", zap.String("category", tmpl.Category), zap.Error(cacheErr))
			}
		}

		return nil
	})
}
