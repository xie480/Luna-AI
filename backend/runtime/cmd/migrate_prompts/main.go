package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/prompt"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
)

// migrateGroup 定义一组模板迁移规则
type migrateGroup struct {
	Name     string // 模板名称，对应文件名
	Category string // 业务分类（chat/summary/lora）
	Slot     string // 槽位类型（system/memory/runtime）
	Vars     []string
	Purpose  string // 说明
}

func main() {
	// Initialize snowflake
	if err := snowflake.InitGlobalNode(1); err != nil {
		log.Fatalf("雪花算法初始化失败: %v", err)
	}

	cfg, err := config.Load("../../.env", "../../config.yaml")
	log.Printf("加载配置失败，使用默认配置: %v", err)
	cfg = &config.Config{}
	cfg.Postgres.Host = "192.168.100.128"
	cfg.Postgres.Port = 5432
	cfg.Postgres.User = "yilena"
	cfg.Postgres.Password = "XUWENBO219382"
	cfg.Postgres.Database = "luna_ai"
	pgClient, err := infrastructure.NewPostgresClient(cfg.PostgresConnStr())
	if err != nil {
		log.Fatalf("PostgreSQL 连接失败: %v", err)
	}
	defer pgClient.Close()

	db := pgClient.GetDB()

	// Auto migrate
	db.AutoMigrate(&repository.PromptTemplate{}, &repository.PromptVersion{})

	promptsDir := "../ai-service/app/templates/prompt/"
	files, err := os.ReadDir(promptsDir)
	if err != nil {
		log.Fatalf("读取提示词目录失败: %v", err)
	}

	// 定义模板迁移映射
	groupMappings := map[string]migrateGroup{
		"system": {
			Category: "chat",
			Slot:     string(prompt.SlotSystem),
			Purpose:  "对话场景 - 系统设定/人设",
		},
		"memory": {
			Category: "chat",
			Slot:     string(prompt.SlotMemory),
			Purpose:  "对话场景 - 记忆上下文",
		},
		"runtime": {
			Category: "chat",
			Slot:     string(prompt.SlotRuntime),
			Purpose:  "对话场景 - 运行时上下文",
		},
	}

	// Summarize 模板拆分为三条 slot 记录，category 为 summary
	summarizeGroups := []migrateGroup{
		{
			Name:    "summarize_system",
			Slot:    string(prompt.SlotSystem),
			Vars:    []string{},
			Purpose: "摘要场景 - 系统设定",
		},
		{
			Name:    "summarize_memory",
			Slot:    string(prompt.SlotMemory),
			Vars:    []string{"CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS"},
			Purpose: "摘要场景 - 记忆上下文",
		},
		{
			Name:    "summarize_runtime",
			Slot:    string(prompt.SlotRuntime),
			Vars:    []string{"MESSAGES_TEXT"},
			Purpose: "摘要场景 - 运行时上下文（待压缩的对话）",
		},
	}

	// 先删除旧的 summarize 模板数据（单条记录的旧模板）
	db.Exec("DELETE FROM prompt_versions WHERE template_id IN (SELECT id FROM prompt_templates WHERE category = 'summarize')")
	db.Exec("DELETE FROM prompt_templates WHERE category = 'summarize'")

	// 插入三条新的 summarize slot 模板
	for _, sg := range summarizeGroups {
		varsJSON, _ := json.Marshal(sg.Vars)

		// 根据 slot 类型读取对应的 .j2 文件并提取对应部分
		content := extractSlotContent(sg.Slot, promptsDir)

		tmpl := repository.PromptTemplate{
			ID:           snowflake.GenerateStringID(),
			Category:     "summary",
			SlotPosition: sg.Slot,
			IsSystem:     true,
		}
		tmpl.Name = sg.Name
		if err := db.Create(&tmpl).Error; err != nil {
			log.Fatalf("创建模板 %s 失败: %v", sg.Name, err)
		}

		// Create version
		version := repository.PromptVersion{
			ID:         snowflake.GenerateStringID(),
			TemplateID: tmpl.ID,
			VersionNum: 1,
			Content:    content,
			Variables:  string(varsJSON),
			Status:     "published",
		}
		if err := db.Create(&version).Error; err != nil {
			log.Fatalf("创建版本 for %s 失败: %v", sg.Name, err)
		}

		// Update active version
		tmpl.ActiveVersionID = version.ID
		if err := db.Save(&tmpl).Error; err != nil {
			log.Fatalf("更新活跃版本 for %s 失败: %v", sg.Name, err)
		}

		fmt.Printf("已迁移 %s (category=summary, slot=%s)\n", sg.Name, sg.Slot)
	}

	// 处理普通对话模板（chat 分类下的 system/memory/runtime）
	for _, file := range files {
		if file.IsDir() || !strings.HasSuffix(file.Name(), ".j2") {
			continue
		}

		name := strings.TrimSuffix(file.Name(), ".j2")

		// 跳过 summarize.j2（已被拆分为三条记录）
		if name == "summarize" {
			continue
		}

		mapping, ok := groupMappings[name]
		if !ok {
			continue
		}

		contentBytes, err := os.ReadFile(filepath.Join(promptsDir, file.Name()))
		if err != nil {
			log.Fatalf("读取文件 %s 失败: %v", file.Name(), err)
		}
		content := string(contentBytes)

		varsJSON, _ := json.Marshal(mapping.Vars)

		// Check if template exists
		var tmpl repository.PromptTemplate
		err = db.Where("name = ?", name).First(&tmpl).Error
		if err != nil {
			// Create template
			tmpl = repository.PromptTemplate{
				ID:           snowflake.GenerateStringID(),
				Name:         name,
				Category:     mapping.Category,
				SlotPosition: mapping.Slot,
				IsSystem:     true,
			}
			if err := db.Create(&tmpl).Error; err != nil {
				log.Fatalf("创建模板 %s 失败: %v", name, err)
			}
		}

		// Create version
		version := repository.PromptVersion{
			ID:         snowflake.GenerateStringID(),
			TemplateID: tmpl.ID,
			VersionNum: 1,
			Content:    content,
			Variables:  string(varsJSON),
			Status:     "published",
		}
		if err := db.Create(&version).Error; err != nil {
			log.Fatalf("创建版本 for %s 失败: %v", name, err)
		}

		// Update active version
		tmpl.ActiveVersionID = version.ID
		if err := db.Save(&tmpl).Error; err != nil {
			log.Fatalf("更新活跃版本 for %s 失败: %v", name, err)
		}

		fmt.Printf("已迁移 %s (category=%s, slot=%s)\n", name, mapping.Category, mapping.Slot)
	}

	fmt.Println("迁移完成。")
}

// extractSlotContent 从 summarize.j2 中提取指定 slot 部分的模板内容
func extractSlotContent(slot, promptsDir string) string {
	contentBytes, err := os.ReadFile(filepath.Join(promptsDir, "summarize.j2"))
	if err != nil {
		log.Fatalf("读取 summarize.j2 失败: %v", err)
	}
	content := string(contentBytes)

	switch slot {
	case "system":
		return extractBetween(content, "【系统指令】", "【记忆上下文】")
	case "memory":
		return extractBetween(content, "【记忆上下文】", "【运行时输入】")
	case "runtime":
		return extractBetween(content, "【运行时输入】", "")
	default:
		return content
	}
}

// extractBetween 提取 start 和 end 标记之间的文本
func extractBetween(s, start, end string) string {
	i := strings.Index(s, start)
	if i < 0 {
		return s
	}
	i += len(start)

	if end == "" {
		return strings.TrimSpace(s[i:])
	}

	j := strings.Index(s[i:], end)
	if j < 0 {
		return strings.TrimSpace(s[i:])
	}
	return strings.TrimSpace(s[i : i+j])
}
