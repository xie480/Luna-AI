package prompt

import (
	"fmt"
	"strings"
)

// SlotPosition 定义 Prompt 槽位类型枚举
type SlotPosition string

const (
	// SlotSystem 系统设定/人设槽位
	SlotSystem SlotPosition = "system"
	// SlotMemory 记忆上下文槽位
	SlotMemory SlotPosition = "memory"
	// SlotRuntime 运行时上下文槽位
	SlotRuntime SlotPosition = "runtime"
)

// ValidSlotPositions 返回所有合法的 SlotPosition 值
func ValidSlotPositions() []SlotPosition {
	return []SlotPosition{SlotSystem, SlotMemory, SlotRuntime}
}

// PromptCategory 定义 Prompt 业务分类枚举
type PromptCategory string

const (
	// CategoryChat 对话场景（槽位: system, memory, runtime）
	CategoryChat PromptCategory = "chat"
	// CategorySummary 摘要压缩场景（槽位: system, memory, runtime）
	CategorySummary PromptCategory = "summary"
)

// 占位符常量
const (
	PlaceholderSystem  = "{system}"
	PlaceholderMemory  = "{memory}"
	PlaceholderRuntime = "{runtime}"
)

// SlotPlaceholders 按注入顺序返回占位符列表
var SlotPlaceholders = []string{PlaceholderSystem, PlaceholderMemory, PlaceholderRuntime}

// SlotPositions 按注入顺序返回 SlotPosition 列表
var SlotPositions = []SlotPosition{SlotSystem, SlotMemory, SlotRuntime}

// renderTemplate 简单渲染 {{ KEY }} 占位符为对应变量的值
func renderTemplate(template string, variables map[string]string) string {
	result := template
	for key, value := range variables {
		// 替换带空格的格式 {{ KEY }}
		placeholderWithSpace := fmt.Sprintf("{{ %s }}", key)
		result = strings.ReplaceAll(result, placeholderWithSpace, value)
		// 替换不带空格的格式 {{KEY}}
		placeholderWithoutSpace := fmt.Sprintf("{{%s}}", key)
		result = strings.ReplaceAll(result, placeholderWithoutSpace, value)
	}
	return result
}
