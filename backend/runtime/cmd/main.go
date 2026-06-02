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

	"luna-ai/backend/runtime/internal/api"
	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/inference"
	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/memory"
	"luna-ai/backend/runtime/internal/prompt"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/telemetry"
	pb "luna-ai/backend/runtime/shared/proto"
)

func main() {
	// 1. 加载配置 - 尝试从 .env 和 config.yaml 文件中读取配置信息
	cfg, err := config.Load(".env", "config.yaml")
	if err != nil {
		log.Printf("加载配置失败，使用默认配置: %v\n", err)
		cfg = &config.Config{}
		cfg.Server.Port = 8080
		cfg.Log.Level = "info"
		cfg.AIService.Address = "localhost:50051"
		cfg.Redis.Host = "localhost"
		cfg.Redis.Port = 6379
		cfg.Redis.Password = ""
		cfg.Redis.DB = 0
		cfg.Postgres.Host = "localhost"
		cfg.Postgres.Port = 5432
		cfg.Postgres.User = "postgres"
		cfg.Postgres.Password = "postgres"
		cfg.Postgres.Database = "luna"
		cfg.Qdrant.Address = "http://localhost:6333"
	}

	// 2. 初始化日志系统
	if err := logger.Init(cfg.Log.Level); err != nil {
		log.Printf("初始化日志系统失败: %v\n", err)
		os.Exit(1)
	}

	ctx := context.Background()
	logger.Info(ctx, "正在启动 Luna 运行时服务", "port", cfg.Server.Port)

	// 3. 初始化 Redis 连接
	redisClient, err := infrastructure.NewRedisClient(cfg.RedisAddr(), cfg.Redis.Password, cfg.Redis.DB)
	if err != nil {
		logger.Warn(ctx, "Redis 连接失败，将使用降级模式运行", "error", err)
	} else {
		defer redisClient.Close()
		logger.Info(ctx, "Redis 连接成功", "addr", cfg.RedisAddr())
	}

	// 4. 初始化 PostgreSQL 连接
	postgresClient, err := infrastructure.NewPostgresClient(cfg.PostgresConnStr())
	if err != nil {
		logger.Warn(ctx, "PostgreSQL 连接失败，将使用降级模式运行", "error", err)
	} else {
		defer postgresClient.Close()
		logger.Info(ctx, "PostgreSQL 连接成功", "database", cfg.Postgres.Database)

		// 自动迁移数据库表结构（包含新加的 long_term_memories 表）
		if err := postgresClient.GetDB().AutoMigrate(
			&repository.InteractionModel{},
			&repository.PromptTemplate{},
			&repository.PromptVersion{},
			&repository.ApiConfigPreset{},
			&repository.LongTermMemory{},
		); err != nil {
			logger.Error(ctx, "自动迁移数据库表结构失败", "error", err)
		} else {
			logger.Info(ctx, "自动迁移数据库表结构成功")
		}

		// 初始化 Telemetry Schema
		if err := telemetry.InitSchema(postgresClient.GetDB()); err != nil {
			logger.Error(ctx, "初始化 Telemetry Schema 失败", "error", err)
		} else {
			logger.Info(ctx, "初始化 Telemetry Schema 成功")
		}

		// 初始化 Telemetry Worker
		telemetry.InitWorker(postgresClient.GetDB())
		go telemetry.GetWorker().Run(ctx)

		// 启动清理任务
		go telemetry.RunCleanup(ctx, postgresClient.GetDB())
	}

	// 初始化监控指标
	telemetry.InitMetrics()
	go telemetry.StartMetricsCollector(ctx)

	// 初始化 CryptoService
	cryptoSvc, err := config.NewCryptoService()
	if err != nil {
		logger.Error(ctx, "初始化 CryptoService 失败", "error", err)
		os.Exit(1)
	}

	// 初始化 AI 客户端
	aiClient, err := api.NewAIClient(cfg.AIService.Address)
	if err != nil {
		logger.Error(ctx, "初始化 AI 客户端失败", "error", err)
		os.Exit(1)
	}
	defer aiClient.Close()

	// 初始化 PromptManager
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

	// 初始化基础设施仓库
	var redisRepo *repository.ChatHistoryRedisRepo
	if redisClient != nil {
		redisRepo = repository.NewChatHistoryRedisRepo(redisClient)
	}
	var pgRepo *repository.ChatHistoryPGRepo
	if postgresClient != nil {
		pgRepo = repository.NewChatHistoryPGRepo(postgresClient)
	}

	// 初始化长期记忆仓库
	var ltmPGRepo *repository.LongTermMemoryPGRepo
	if postgresClient != nil {
		ltmPGRepo = repository.NewLongTermMemoryPGRepo(postgresClient)
	}
	var qdrantClient *infrastructure.QdrantClient
	var ltmQdrantRepo *repository.LongTermMemoryQdrantRepo
	if cfg.Qdrant.Address != "" {
		qdrantClient, err = infrastructure.NewQdrantClient(cfg.Qdrant.Address)
		if err != nil {
			logger.Warn(ctx, "Qdrant 连接失败，将使用降级模式", "error", err)
		}
		if qdrantClient != nil {
			ltmQdrantRepo = repository.NewLongTermMemoryQdrantRepo(qdrantClient)
		}
	}

	// 初始化推理服务
	var inferenceSvc inference.Service
	if aiClient != nil {
		inferenceSvc = inference.NewService(aiClient)
	}

	// 初始化长期记忆管理器并执行启动时兜底检测
	var memoryManager *memory.Manager
	if ltmPGRepo != nil {
		topK := cfg.Retrieval.TopK
		if topK <= 0 {
			topK = 5 // 默认值
		}
		memoryManager = memory.NewManager(redisRepo, ltmPGRepo, ltmQdrantRepo, aiClient, promptManager, qdrantClient, inferenceSvc, topK)
		if err := memoryManager.Init(ctx); err != nil {
			logger.Error(ctx, "长期记忆系统初始化失败", "error", err)
		} else {
			logger.Info(ctx, "长期记忆系统初始化成功")
		}
	}

	// 6. 注册路由
	mux := http.NewServeMux()

	if postgresClient != nil && aiClient != nil {
		presetRepo := repository.NewConfigPresetPGRepo(postgresClient)
		eventBus := config.NewEventBus()
		configMgr := config.NewManager(presetRepo, cryptoSvc, eventBus)
		presetHandler := api.NewApiConfigPresetHandler(presetRepo, cryptoSvc, aiClient, configMgr)
		mux.HandleFunc("GET /api/v1/config/presets", presetHandler.HandleGetPresets)
		mux.HandleFunc("POST /api/v1/config/presets", presetHandler.HandleSavePreset)
		mux.HandleFunc("POST /api/v1/config/presets/{id}/activate", presetHandler.HandleActivatePreset)
		mux.HandleFunc("DELETE /api/v1/config/presets/{id}", presetHandler.HandleDeletePreset)
		mux.HandleFunc("POST /api/v1/models/fetch", presetHandler.HandleFetchModels)

		eventHandler := func(event config.Event) {
			if event.Type == config.EventConfigChanged {
				snapshot, ok := event.Data.(*config.ActiveConfigSnapshot)
				if !ok || snapshot == nil {
					return
				}
				syncReq := &pb.SyncPresetConfigRequest{
					SchemaVersion: "v1.0",
					PresetId:      snapshot.PresetID,
					LargeModel: &pb.ModelConfig{
						BaseUrl:     snapshot.LargeModelConfig.BaseURL,
						ApiKey:      snapshot.LargeModelConfig.APIKey,
						ModelId:          snapshot.LargeModelConfig.ModelID,
						MaxTokens:        snapshot.LargeModelConfig.MaxTokens,
						MaxContextTokens: snapshot.LargeModelConfig.MaxContextTokens,
						Temperature:      snapshot.LargeModelConfig.Temperature,
					},
					MediumModel: &pb.ModelConfig{
						BaseUrl:          snapshot.MediumModelConfig.BaseURL,
						ApiKey:           snapshot.MediumModelConfig.APIKey,
						ModelId:          snapshot.MediumModelConfig.ModelID,
						MaxTokens:        snapshot.MediumModelConfig.MaxTokens,
						MaxContextTokens: snapshot.MediumModelConfig.MaxContextTokens,
						Temperature:      snapshot.MediumModelConfig.Temperature,
					},
					SmallModel: &pb.ModelConfig{
						BaseUrl:          snapshot.SmallModelConfig.BaseURL,
						ApiKey:           snapshot.SmallModelConfig.APIKey,
						ModelId:          snapshot.SmallModelConfig.ModelID,
						MaxTokens:        snapshot.SmallModelConfig.MaxTokens,
						MaxContextTokens: snapshot.SmallModelConfig.MaxContextTokens,
						Temperature:      snapshot.SmallModelConfig.Temperature,
					},
				}
				_, _ = aiClient.SyncPresetConfig(context.Background(), syncReq)
			}
		}
		eventBus.Subscribe(config.EventConfigChanged, eventHandler)

		if err := configMgr.LoadActiveConfig(ctx); err != nil {
			logger.Error(ctx, "加载激活配置失败", "error", err)
		} else {
			snapshot := configMgr.GetActiveConfig()
			if snapshot != nil && snapshot.PresetID != "" {
				logger.Info(ctx, "加载到激活配置，准备触发初始同步", "preset_id", snapshot.PresetID)
				go func() {
					maxRetries := 15
					for i := 0; i < maxRetries; i++ {
						_, err := aiClient.Ping(context.Background(), "init-sync")
						if err == nil {
							eventBus.Publish(config.Event{
								Type: config.EventConfigChanged,
								Data: snapshot,
							})
							logger.Info(context.Background(), "初始配置同步成功")
							return
						}
						time.Sleep(2 * time.Second)
					}
					logger.Error(context.Background(), "初始配置同步失败：AI 服务未就绪")
				}()
			} else {
				logger.Info(ctx, "当前没有激活的配置预设")
			}
		}
	}

	// Prompt 端点
	if promptManager != nil {
		promptHandler := api.NewPromptHandler(promptManager)
		mux.HandleFunc("GET /api/v1/prompts/templates/{id}/versions", promptHandler.HandleGetVersions)
		mux.HandleFunc("GET /api/v1/prompts/templates", promptHandler.HandleGetTemplates)
		mux.HandleFunc("POST /api/v1/prompts/template", promptHandler.HandleCreateTemplate)
		mux.HandleFunc("POST /api/v1/prompts/version", promptHandler.HandleCreateVersion)
		mux.HandleFunc("POST /api/v1/prompts/publish", promptHandler.HandlePublishVersion)
		mux.HandleFunc("POST /api/v1/prompts/rollback", promptHandler.HandleRollbackVersion)
	}

	// Telemetry 端点
	if postgresClient != nil {
		telemetryHandler := api.NewTelemetryHandler(postgresClient.GetDB())
		mux.HandleFunc("GET /api/v1/telemetry/traces", telemetryHandler.GetTraces)
		mux.HandleFunc("GET /api/v1/telemetry/audit_logs", telemetryHandler.GetAuditLogs)
		mux.HandleFunc("GET /api/v1/telemetry/metrics", telemetryHandler.GetMetrics)
	}

	// 健康检查端点
	healthHandler := api.NewHealthHandler(aiClient, redisClient, postgresClient)
	mux.HandleFunc("/health", healthHandler.HandleHealthCheck)

	// WebSocket 端点 - 传递 memoryManager 以便前端事件通知
	wsServer := api.NewWSServer(aiClient, redisRepo, pgRepo, promptManager, memoryManager)
	mux.HandleFunc("/ws", wsServer.HandleWS)

	// 定义 CORS 中间件
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

	// 7. 启动 HTTP 服务
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Server.Port),
		Handler: corsMiddleware(mux),
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error(ctx, "启动服务器失败", "error", err)
			os.Exit(1)
		}
	}()

	// 启动会话流转定时检测（每分钟检查是否需要跨天流转）
	if memoryManager != nil {
		go func() {
			ticker := time.NewTicker(1 * time.Minute)
			defer ticker.Stop()
			currentSessionID := time.Now().Format("20060102")
			for range ticker.C {
				newSessionID, err := memoryManager.RolloverSession(context.Background(), currentSessionID)
				if err != nil {
					logger.Error(context.Background(), "会话流转检测失败", "error", err)
				} else {
					currentSessionID = newSessionID
				}
			}
		}()
	}

	// 8. 实现优雅退出
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info(ctx, "正在关闭服务器...")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error(ctx, "服务器强制关闭", "error", err)
	}

	logger.Info(ctx, "服务器已退出")
}
