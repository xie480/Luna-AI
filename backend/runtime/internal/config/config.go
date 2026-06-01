package config

import (
	"fmt"
	"os"
	"strconv"

	"github.com/joho/godotenv"
	"gopkg.in/yaml.v3"
)

// Config 定义全局配置结构
// 包含服务器、日志、AI服务、Redis、PostgreSQL、Qdrant 等所有配置项
type Config struct {
	// HTTP 服务器配置
	Server struct {
		// 监听端口
		Port int `yaml:"port"`
	} `yaml:"server"`

	// 日志配置
	Log struct {
		// 日志级别: debug, info, warn, error
		Level string `yaml:"level"`
	} `yaml:"log"`

	// AI 服务配置
	AIService struct {
		// Python AI 服务 gRPC 地址
		Address string `yaml:"address"`
	} `yaml:"ai_service"`

	// Redis 配置 - 用于 DAG 工作流状态同步与 Event Bus
	Redis struct {
		// Redis 服务器地址
		Host string `yaml:"host"`
		// Redis 服务器端口
		Port int `yaml:"port"`
		// Redis 密码（本地开发通常为空）
		Password string `yaml:"password"`
		// Redis 数据库编号
		DB int `yaml:"db"`
	} `yaml:"redis"`

	// PostgreSQL 配置 - 用于配置、记忆、状态持久化
	Postgres struct {
		// PostgreSQL 服务器地址
		Host string `yaml:"host"`
		// PostgreSQL 服务器端口
		Port int `yaml:"port"`
		// PostgreSQL 用户名
		User string `yaml:"user"`
		// PostgreSQL 密码
		Password string `yaml:"password"`
		// PostgreSQL 数据库名
		Database string `yaml:"database"`
	} `yaml:"postgres"`

	// Qdrant 配置 - 用于向量检索
	Qdrant struct {
		// Qdrant HTTP API 地址
		Address string `yaml:"address"`
	} `yaml:"qdrant"`
}

// Load 加载配置
// 优先从环境变量读取，其次从 YAML 配置文件读取
// 参数:
//   - envPath: .env 文件路径（可选）
//   - yamlPath: YAML 配置文件路径
// 返回:
//   - *Config: 配置结构体指针
//   - error: 错误信息
func Load(envPath, yamlPath string) (*Config, error) {
	// 1. 加载 .env 文件 (可选，失败不报错)
	_ = godotenv.Load(envPath)

	// 2. 加载 yaml 配置文件
	data, err := os.ReadFile(yamlPath)
	if err != nil {
		return nil, fmt.Errorf("读取配置文件失败: %w", err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("解析配置文件失败: %w", err)
	}

	// 3. 环境变量覆盖 YAML 配置（优先级更高）
	applyEnvOverrides(&cfg)

	return &cfg, nil
}

// applyEnvOverrides 使用环境变量覆盖配置
// 环境变量命名规则: SERVER_PORT, LOG_LEVEL, REDIS_HOST 等
func applyEnvOverrides(cfg *Config) {
	// 服务器配置
	if port := getEnvInt("SERVER_PORT"); port != 0 {
		cfg.Server.Port = port
	}

	// 日志配置
	if level := getEnvString("LOG_LEVEL"); level != "" {
		cfg.Log.Level = level
	}

	// AI 服务配置
	if addr := getEnvString("AI_SERVICE_ADDRESS"); addr != "" {
		cfg.AIService.Address = addr
	}

	// Redis 配置
	if host := getEnvString("REDIS_HOST"); host != "" {
		cfg.Redis.Host = host
	}
	if port := getEnvInt("REDIS_PORT"); port != 0 {
		cfg.Redis.Port = port
	}
	if password := getEnvString("REDIS_PASSWORD"); password != "" {
		cfg.Redis.Password = password
	}
	if db := getEnvInt("REDIS_DB"); db != 0 {
		cfg.Redis.DB = db
	}

	// PostgreSQL 配置
	if host := getEnvString("DB_HOST"); host != "" {
		cfg.Postgres.Host = host
	}
	if port := getEnvInt("DB_PORT"); port != 0 {
		cfg.Postgres.Port = port
	}
	if user := getEnvString("DB_USER"); user != "" {
		cfg.Postgres.User = user
	}
	if password := getEnvString("DB_PASSWORD"); password != "" {
		cfg.Postgres.Password = password
	}
	if database := getEnvString("DB_NAME"); database != "" {
		cfg.Postgres.Database = database
	}

	// Qdrant 配置
	if addr := getEnvString("QDRANT_ADDRESS"); addr != "" {
		cfg.Qdrant.Address = addr
	}
}

// getEnvString 获取环境变量字符串值
// 如果环境变量不存在，返回空字符串
func getEnvString(key string) string {
	return os.Getenv(key)
}

// getEnvInt 获取环境变量整数值
// 如果环境变量不存在或解析失败，返回 0
func getEnvInt(key string) int {
	val := os.Getenv(key)
	if val == "" {
		return 0
	}
	intVal, err := strconv.Atoi(val)
	if err != nil {
		return 0
	}
	return intVal
}

// RedisAddr 返回 Redis 连接地址字符串
// 格式: host:port
func (c *Config) RedisAddr() string {
	return fmt.Sprintf("%s:%d", c.Redis.Host, c.Redis.Port)
}

// PostgresConnStr 返回 PostgreSQL 连接字符串
// 格式: postgres://user:password@host:port/database
func (c *Config) PostgresConnStr() string {
	return fmt.Sprintf(
		"postgres://%s:%s@%s:%d/%s",
		c.Postgres.User,
		c.Postgres.Password,
		c.Postgres.Host,
		c.Postgres.Port,
		c.Postgres.Database,
	)
}
