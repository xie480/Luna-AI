package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfig(t *testing.T) {
	// Create temp dir for test files
	tempDir := t.TempDir()
	envPath := filepath.Join(tempDir, ".env")
	yamlPath := filepath.Join(tempDir, "config.yaml")

	// Write mock .env
	envContent := []byte("TEST_ENV=123\n")
	if err := os.WriteFile(envPath, envContent, 0644); err != nil {
		t.Fatal(err)
	}

	// Write mock config.yaml
	yamlContent := []byte(`
server:
  port: 8080
log:
  level: debug
`)
	if err := os.WriteFile(yamlPath, yamlContent, 0644); err != nil {
		t.Fatal(err)
	}

	// Test Load
	cfg, err := Load(envPath, yamlPath)
	if err != nil {
		t.Fatalf("failed to load config: %v", err)
	}

	if cfg.Server.Port != 8080 {
		t.Errorf("expected port 8080, got %d", cfg.Server.Port)
	}

	if cfg.Log.Level != "debug" {
		t.Errorf("expected log level debug, got %s", cfg.Log.Level)
	}
}
