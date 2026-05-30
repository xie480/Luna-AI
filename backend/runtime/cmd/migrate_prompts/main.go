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
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
)

func main() {
	// Initialize snowflake
	if err := snowflake.InitGlobalNode(1); err != nil {
		log.Fatalf("Failed to init snowflake: %v", err)
	}

	cfg, err := config.Load("../../.env", "../../config.yaml")
	log.Printf("Failed to load config, using defaults: %v", err)
	cfg = &config.Config{}
	cfg.Postgres.Host = "192.168.100.128"
	cfg.Postgres.Port = 5432
	cfg.Postgres.User = "yilena"
	cfg.Postgres.Password = "XUWENBO219382"
	cfg.Postgres.Database = "luna_ai"
	pgClient, err := infrastructure.NewPostgresClient(cfg.PostgresConnStr())
	if err != nil {
		log.Fatalf("Failed to connect to postgres: %v", err)
	}
	defer pgClient.Close()

	db := pgClient.GetDB()

	// Auto migrate
	db.AutoMigrate(&repository.PromptTemplate{}, &repository.PromptVersion{})

	promptsDir := "../ai-service/app/templates/prompt/"
	files, err := os.ReadDir(promptsDir)
	if err != nil {
		log.Fatalf("Failed to read prompts dir: %v", err)
	}

	for _, file := range files {
		if file.IsDir() || !strings.HasSuffix(file.Name(), ".j2") {
			continue
		}

		name := strings.TrimSuffix(file.Name(), ".j2")
		contentBytes, err := os.ReadFile(filepath.Join(promptsDir, file.Name()))
		if err != nil {
			log.Fatalf("Failed to read file %s: %v", file.Name(), err)
		}
		content := string(contentBytes)

		var variables []string
		if name == "memory" {
			variables = []string{"CORE_SUMMARY", "KEY_FACTS", "MEMORY_SNIPPETS"}
		} else if name == "runtime" {
			variables = []string{"CURRENT_TIME", "CURRENT_MESSAGE"}
		} else if name == "summarize" {
			variables = []string{"CURRENT_CORE_SUMMARY", "CURRENT_KEY_FACTS", "MESSAGES_TEXT"}
		}

		varsJSON, _ := json.Marshal(variables)

		// Check if template exists
		var tmpl repository.PromptTemplate
		err = db.Where("name = ?", name).First(&tmpl).Error
		if err != nil {
			// Create template
			tmpl = repository.PromptTemplate{
				ID:           snowflake.GenerateStringID(),
				Name:         name,
				Category:     "system",
				SlotPosition: name,
				IsSystem:     true,
			}
			if err := db.Create(&tmpl).Error; err != nil {
				log.Fatalf("Failed to create template %s: %v", name, err)
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
			log.Fatalf("Failed to create version for %s: %v", name, err)
		}

		// Update active version
		tmpl.ActiveVersionID = version.ID
		if err := db.Save(&tmpl).Error; err != nil {
			log.Fatalf("Failed to update active version for %s: %v", name, err)
		}

		fmt.Printf("Migrated %s\n", name)
	}
	fmt.Println("Migration completed successfully.")
}
