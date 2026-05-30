package prompt

import (
	"context"
	"fmt"
	"strings"
	"time"

	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"

	"go.uber.org/zap"
)

// Manager 负责 Prompt 模板与版本的管理
type Manager struct {
	repo *repository.PromptPGRepo
}

// NewManager 创建 Manager
func NewManager(repo *repository.PromptPGRepo) *Manager {
	return &Manager{
		repo: repo,
	}
}

// AssembleChatPrompt 根据业务场景组装完整的 Chat System Prompt
// 输入：
//   - ctx: 上下文
//   - category: 业务分类（如 "chat"）
//   - variables: 注入模板的变量键值对
//
// 输出：
//   - 完整的 system_prompt 字符串
//   - 错误信息
func (m *Manager) AssembleChatPrompt(ctx context.Context, category string, variables map[string]string) (string, error) {
	templates, err := m.repo.GetTemplatesByCategory(ctx, category)
	if err != nil {
		logger.Warn(ctx, "从数据库获取 Prompt 模板失败", zap.Error(err))
		return err.Error(), nil
	}

	// 按 SlotPosition 的顺序组装各层模板内容
	// 组装顺序：system (人设) -> memory (记忆) -> runtime (运行时)
	var systemParts []string

	for _, tmpl := range templates {
		if tmpl.ActiveVersionID == "" {
			continue
		}

		version, err := m.repo.GetVersion(ctx, tmpl.ActiveVersionID)
		if err != nil {
			logger.Warn(ctx, "获取模板版本失败，跳过", zap.String("template_name", tmpl.Name), zap.Error(err))
			continue
		}

		// 渲染模板：替换 {{ KEY }} 占位符
		rendered := renderTemplate(version.Content, variables)

		// 根据 slot_position 分类组装
		if tmpl.SlotPosition == "system" || tmpl.SlotPosition == "memory" || tmpl.SlotPosition == "runtime" {
			systemParts = append(systemParts, rendered)
		}
	}

	// 组装完整的 system_prompt
	fullPrompt := strings.TrimSpace(strings.Join(systemParts, "\n\n"))

	logger.Info(ctx, "组装 Chat Prompt 成功",
		zap.Int("template_count", len(systemParts)),
		zap.Int("prompt_length", len(fullPrompt)))

	return fullPrompt, nil
}

// AssembleSummarizePrompt 组装完整的 Summarize Prompt
// 输入：
//   - ctx: 上下文
//   - variables: 注入模板的变量键值对
//     需要包含: CURRENT_CORE_SUMMARY, CURRENT_KEY_FACTS, MESSAGES_TEXT
//
// 输出：
//   - 完整的 summarize_prompt 字符串
//   - 错误信息
func (m *Manager) AssembleSummarizePrompt(ctx context.Context, variables map[string]string) (string, error) {
	templates, err := m.repo.GetTemplatesByCategory(ctx, "summarize")
	if err != nil {
		logger.Warn(ctx, "从数据库获取 Summarize 模板失败，使用硬编码兜底", zap.Error(err))
		return FallbackSummarizePrompt(variables), nil
	}

	for _, tmpl := range templates {
		if tmpl.ActiveVersionID == "" {
			continue
		}
		version, err := m.repo.GetVersion(ctx, tmpl.ActiveVersionID)
		if err != nil {
			continue
		}
		return renderTemplate(version.Content, variables), nil
	}

	// 兜底
	logger.Warn(ctx, "组装 Summarize Prompt 失败，使用硬编码兜底")
	return FallbackSummarizePrompt(variables), nil
}

// renderTemplate 简单渲染 {{ KEY }} 占位符为对应变量的值
// 不兼容 Jinja2 语法，只支持 {{ VARIABLE_NAME }} 格式的简单替换
func renderTemplate(template string, variables map[string]string) string {
	result := template
	for key, value := range variables {
		placeholder := fmt.Sprintf("{{ %s }}", key)
		result = strings.ReplaceAll(result, placeholder, value)
	}
	return result
}

// FallbackChatPrompt 硬编码兜底的 Chat Prompt
func FallbackChatPrompt(variables map[string]string) string {
	currentTime := variables["CURRENT_TIME"]
	if currentTime == "" {
		currentTime = time.Now().Format("2006-01-02 15:04:05 Monday")
	}
	currentMessage := variables["CURRENT_MESSAGE"]
	coreSummary := variables["CORE_SUMMARY"]
	keyFacts := variables["KEY_FACTS"]
	memorySnippets := variables["MEMORY_SNIPPETS"]

	var b strings.Builder
	b.WriteString(`你是一个名为 Luna 的 AI 助手。
请使用 JSON 格式输出，包含 thought, emotion, reply 三个字段。

当前系统时间：
`)
	b.WriteString(currentTime)
	b.WriteString("\n\n")
	b.WriteString("用户输入：\n")
	b.WriteString(currentMessage)
	b.WriteString("\n\n")

	if coreSummary != "" {
		b.WriteString("核心摘要：\n")
		b.WriteString(coreSummary)
		b.WriteString("\n\n")
	}
	if keyFacts != "" {
		b.WriteString("关键事实：\n")
		b.WriteString(keyFacts)
		b.WriteString("\n\n")
	}
	if memorySnippets != "" {
		b.WriteString("历史对话：\n")
		b.WriteString(memorySnippets)
		b.WriteString("\n\n")
	}

	return b.String()
}

// FallbackSummarizePrompt 硬编码兜底的 Summarize Prompt
func FallbackSummarizePrompt(variables map[string]string) string {
	currentSummary := variables["CURRENT_CORE_SUMMARY"]
	currentFacts := variables["CURRENT_KEY_FACTS"]
	messagesText := variables["MESSAGES_TEXT"]

	var b strings.Builder
	b.WriteString(`请对以下对话内容进行摘要压缩。

当前核心摘要：
`)
	b.WriteString(currentSummary)
	b.WriteString("\n\n当前关键事实：\n")
	b.WriteString(currentFacts)
	b.WriteString("\n\n需要压缩的对话：\n")
	b.WriteString(messagesText)
	b.WriteString("\n\n请以 JSON 格式输出 core_summary 和 key_facts。")

	return b.String()
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

	return nil
}
