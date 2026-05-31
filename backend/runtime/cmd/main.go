/*
 * 启动服务
 * 该程序负责启动 Luna 运行时服务，包括配置加载、日志初始化、基础设施连接、HTTP服务器启动和优雅关闭等功能
 */
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/api"
	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/prompt"
	"luna-ai/backend/runtime/internal/repository"
)

func main() {
	// 1. 加载配置 - 尝试从 .env 和 config.yaml 文件中读取配置信息
	cfg, err := config.Load(".env", "config.yaml")
	if err != nil {
		// 如果配置文件不存在或读取失败，则使用默认配置值
		log.Printf("加载配置失败，使用默认配置: %v\n", err)
		cfg = &config.Config{}
		cfg.Server.Port = 8080      // 默认运行在 8080 端口
		cfg.Log.Level = "info"      // 默认日志级别为 info
		cfg.AIService.Address = "localhost:50051"
		// Redis 默认配置
		cfg.Redis.Host = "localhost"
		cfg.Redis.Port = 6379
		cfg.Redis.Password = ""
		cfg.Redis.DB = 0
		// PostgreSQL 默认配置
		cfg.Postgres.Host = "localhost"
		cfg.Postgres.Port = 5432
		cfg.Postgres.User = "postgres"
		cfg.Postgres.Password = "postgres"
		cfg.Postgres.Database = "luna"
	}

	// 2. 初始化日志系统 - 根据配置的日志级别设置日志记录器
	if err := logger.Init(cfg.Log.Level); err != nil {
		log.Printf("初始化日志系统失败: %v\n", err)
		os.Exit(1)
	}
	// 程序结束前确保所有日志都被写入到输出
	defer logger.Sync()

	ctx := context.Background()
	// 记录服务启动日志，包含监听的端口号
	logger.Info(ctx, "正在启动 Luna 运行时服务", zap.Int("port", cfg.Server.Port))

	// 3. 初始化 Redis 连接 - 用于 DAG 工作流状态同步与 Event Bus
	redisClient, err := infrastructure.NewRedisClient(cfg.RedisAddr(), cfg.Redis.Password, cfg.Redis.DB)
	if err != nil {
		logger.Warn(ctx, "Redis 连接失败，将使用降级模式运行", zap.Error(err))
		// Redis 连接失败不阻止服务启动，后续可降级处理
	} else {
		defer redisClient.Close()
		logger.Info(ctx, "Redis 连接成功", zap.String("addr", cfg.RedisAddr()))
	}

	// 4. 初始化 PostgreSQL 连接 - 用于配置、记忆、状态持久化
	postgresClient, err := infrastructure.NewPostgresClient(cfg.PostgresConnStr())
	if err != nil {
		logger.Warn(ctx, "PostgreSQL 连接失败，将使用降级模式运行", zap.Error(err))
		// PostgreSQL 连接失败不阻止服务启动，后续可降级处理
	} else {
		defer postgresClient.Close()
		logger.Info(ctx, "PostgreSQL 连接成功", zap.String("database", cfg.Postgres.Database))
		
		// 自动迁移数据库表结构
		if err := postgresClient.GetDB().AutoMigrate(
			&repository.InteractionModel{},
			&repository.SystemConfig{},
			&repository.PromptTemplate{},
			&repository.PromptVersion{},
			&repository.ApiConfigPreset{},
		); err != nil {
			logger.Error(ctx, "自动迁移数据库表结构失败", zap.Error(err))
		} else {
			logger.Info(ctx, "自动迁移数据库表结构成功")
		}
	}

	// 初始化 CryptoService
	cryptoSvc, err := config.NewCryptoService()
	if err != nil {
		logger.Error(ctx, "初始化 CryptoService 失败", zap.Error(err))
		os.Exit(1)
	}

	// 初始化 EventBus
	eventBus := config.NewEventBus()

	// 初始化 ConfigManager
	var configManager *config.ConfigManager
	if postgresClient != nil {
		configRepo := repository.NewConfigPGRepo(postgresClient)
		configManager, err = config.NewConfigManager(configRepo, cryptoSvc, eventBus)
		if err != nil {
			logger.Error(ctx, "初始化 ConfigManager 失败", zap.Error(err))
			os.Exit(1)
		}
	}

	// 初始化 PromptManager（传入 redisClient，启用懒加载缓存）
	var promptManager *prompt.Manager
	if postgresClient != nil {
		promptRepo := repository.NewPromptPGRepo(postgresClient)
		var redisClientForCache *redis.Client
		if redisClient != nil {
			redisClientForCache = redisClient.GetClient()
		}
		promptCache := prompt.NewCacheManager(redisClientForCache, promptRepo)
		promptManager = prompt.NewManager(promptRepo, promptCache)
	}

	// 5. 初始化 AI 客户端 - 连接 Python AI 服务
	aiClient, err := api.NewAIClient(cfg.AIService.Address)
	if err != nil {
		logger.Error(ctx, "初始化 AI 客户端失败", zap.Error(err))
		os.Exit(1)
	}
	defer aiClient.Close()

	// 6. 注册路由 - 设置 HTTP 路由处理器
	mux := http.NewServeMux()

	// 配置端点（Go 1.22+ 方法路由模式）
	if configManager != nil && aiClient != nil {
		configHandler := api.NewConfigHandler(configManager, aiClient)
		mux.HandleFunc("GET /api/v1/config", configHandler.HandleGetConfig)
		mux.HandleFunc("POST /api/v1/config", configHandler.HandleUpdateConfig)
	}

	// API 配置预设端点
	if postgresClient != nil && aiClient != nil {
		presetRepo := repository.NewConfigPresetPGRepo(postgresClient)
		presetHandler := api.NewApiConfigPresetHandler(presetRepo, cryptoSvc, aiClient)
		mux.HandleFunc("GET /api/v1/config/presets", presetHandler.HandleGetPresets)
		mux.HandleFunc("POST /api/v1/config/presets", presetHandler.HandleSavePreset)
		mux.HandleFunc("POST /api/v1/config/presets/{id}/activate", presetHandler.HandleActivatePreset)
		mux.HandleFunc("DELETE /api/v1/config/presets/{id}", presetHandler.HandleDeletePreset)
		mux.HandleFunc("POST /api/v1/models/fetch", presetHandler.HandleFetchModels)
	}

	// Prompt 端点（Go 1.22+ 方法路由模式 + 路径参数）
	if promptManager != nil {
		promptHandler := api.NewPromptHandler(promptManager)
		mux.HandleFunc("GET /api/v1/prompts/templates/{id}/versions", promptHandler.HandleGetVersions)
		mux.HandleFunc("GET /api/v1/prompts/templates", promptHandler.HandleGetTemplates)
		mux.HandleFunc("POST /api/v1/prompts/template", promptHandler.HandleCreateTemplate)
		mux.HandleFunc("POST /api/v1/prompts/version", promptHandler.HandleCreateVersion)
		mux.HandleFunc("POST /api/v1/prompts/publish", promptHandler.HandlePublishVersion)
		mux.HandleFunc("POST /api/v1/prompts/rollback", promptHandler.HandleRollbackVersion)
	}

	// 健康检查端点 - 包含三层健康状态检查
	healthHandler := api.NewHealthHandler(aiClient, redisClient, postgresClient)
	mux.HandleFunc("/health", healthHandler.HandleHealthCheck)

	// WebSocket 端点 - 前端通信入口
	// 注意：redisClient 和 postgresClient 可能为 nil（连接失败时），仓库层需处理 nil 情况
	var redisRepo *repository.ChatHistoryRedisRepo
	if redisClient != nil {
		redisRepo = repository.NewChatHistoryRedisRepo(redisClient)
	}
	var pgRepo *repository.ChatHistoryPGRepo
	if postgresClient != nil {
		pgRepo = repository.NewChatHistoryPGRepo(postgresClient)
	}
	wsServer := api.NewWSServer(aiClient, redisRepo, pgRepo, promptManager)
	mux.HandleFunc("/ws", wsServer.HandleWS)

	// 定义 CORS 中间件，允许前端跨域请求 HTTP 接口
	corsMiddleware := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Access-Control-Allow-Origin", "*")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
			if r.Method == "OPTIONS" {
				w.WriteHeader(http.StatusOK)
				return
			}
			next.ServeHTTP(w, r)
		})
	}

	// 7. 启动 HTTP 服务 - 创建并启动 HTTP 服务器
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Server.Port), // 监听地址
		Handler: corsMiddleware(mux),                  // 包装 CORS 中间件
	}

	// 在独立的 goroutine 中启动服务器，避免阻塞主程序流程
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error(ctx, "启动服务器失败", zap.Error(err))
			os.Exit(1)
		}
	}()

	// 8. 实现优雅退出 - 监听系统信号以实现平滑关闭
	quit := make(chan os.Signal, 1)
	// 监听 SIGINT (Ctrl+C) 和 SIGTERM (系统终止) 信号
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	// 阻塞等待接收到退出信号
	<-quit
	logger.Info(ctx, "正在关闭服务器...")

	// 创建带超时的上下文，确保关闭操作不会无限期等待
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// 尝试优雅地关闭服务器，等待正在进行的请求处理完毕
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error(ctx, "服务器强制关闭", zap.Error(err))
	}

	logger.Info(ctx, "服务器已退出")
}
