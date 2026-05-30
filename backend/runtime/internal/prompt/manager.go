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

// Manager 负责 Prompt 模板与版本的管理
type Manager struct {
	repo       *repository.PromptPGRepo
	cacheMgr   *CacheManager
}

// NewManager 创建 Manager
func NewManager(repo *repository.PromptPGRepo, cacheMgr *CacheManager) *Manager {
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
	tmpl, err := m.repo.GetTemplate(ctx, templateID)
	if err != nil {
		return err
	}

	// 验证版本是否存在
	version, err := m.repo.GetVersion(ctx, versionID)
	if err != nil {
		return err
	}

	if version.TemplateID != templateID {
		return fmt.Errorf("版本 %s 不属于模板 %s", versionID, templateID)
	}

	tmpl.ActiveVersionID = versionID
	if err := m.repo.UpdateTemplate(ctx, tmpl); err != nil {
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
}
