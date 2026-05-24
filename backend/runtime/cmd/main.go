package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"luna-ai/backend/runtime/internal/api"
	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/logger"

	"go.uber.org/zap"
)

func main() {
	// 1. 加载配置
	cfg, err := config.Load(".env", "config.yaml")
	if err != nil {
		// 如果配置文件不存在，使用默认配置
		fmt.Printf("Failed to load config, using defaults: %v\n", err)
		cfg = &config.Config{}
		cfg.Server.Port = 8080
		cfg.Log.Level = "info"
	}

	// 2. 初始化日志
	if err := logger.Init(cfg.Log.Level); err != nil {
		fmt.Printf("Failed to initialize logger: %v\n", err)
		os.Exit(1)
	}
	defer logger.Sync()

	ctx := context.Background()
	logger.Info(ctx, "Starting Luna Runtime", zap.Int("port", cfg.Server.Port))

	// 3. 注册路由
	mux := http.NewServeMux()
	mux.HandleFunc("/health", api.HealthCheckHandler)

	// 4. 启动 HTTP 服务
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Server.Port),
		Handler: mux,
	}

	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error(ctx, "Failed to start server", zap.Error(err))
			os.Exit(1)
		}
	}()

	// 5. 优雅退出
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info(ctx, "Shutting down server...")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error(ctx, "Server forced to shutdown", zap.Error(err))
	}

	logger.Info(ctx, "Server exiting")
}
