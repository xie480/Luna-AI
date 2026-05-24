/*
 * 启动服务
 * 该程序负责启动 Luna 运行时服务，包括配置加载、日志初始化、HTTP服务器启动和优雅关闭等功能
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

	"luna-ai/backend/runtime/internal/api"
	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/logger"

	"go.uber.org/zap"
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

	// 3. 初始化 AI 客户端
	aiClient, err := api.NewAIClient(cfg.AIService.Address)
	if err != nil {
		logger.Error(ctx, "初始化 AI 客户端失败", zap.Error(err))
		os.Exit(1)
	}
	defer aiClient.Close()

	// 4. 注册路由 - 设置 HTTP 路由处理器
	mux := http.NewServeMux()
	// 健康检查端点，用于确认服务是否正常运行
	mux.HandleFunc("/health", api.HealthCheckHandler)

	// WebSocket 端点
	wsServer := api.NewWSServer(aiClient)
	mux.HandleFunc("/ws", wsServer.HandleWS)

	// 5. 启动 HTTP 服务 - 创建并启动 HTTP 服务器
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Server.Port),  // 监听地址
		Handler: mux,                                   // 请求处理器
	}

	// 在独立的 goroutine 中启动服务器，避免阻塞主程序流程
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error(ctx, "启动服务器失败", zap.Error(err))
			os.Exit(1)
		}
	}()

	// 6. 实现优雅退出 - 监听系统信号以实现平滑关闭
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
