package config

import (
	"os"

	"github.com/joho/godotenv"
	"gopkg.in/yaml.v3"
)

// Config 定义全局配置结构
type Config struct {
	Server struct {
		Port int `yaml:"port"`
	} `yaml:"server"`
	Log struct {
		Level string `yaml:"level"`
	} `yaml:"log"`
}

// Load 加载配置
func Load(envPath, yamlPath string) (*Config, error) {
	// 1. 加载 .env 文件 (可选)
	_ = godotenv.Load(envPath)

	// 2. 加载 yaml 配置
	data, err := os.ReadFile(yamlPath)
	if err != nil {
		return nil, err
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}

	return &cfg, nil
}
