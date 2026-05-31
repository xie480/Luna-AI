package logger

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"

	"gopkg.in/natefinch/lumberjack.v2"
)

// ContextKey 定义上下文键类型
type ContextKey string

const (
	// TraceIDKey 链路追踪 ID
	TraceIDKey ContextKey = "trace_id"
	// NodeIDKey 节点 ID
	NodeIDKey ContextKey = "node_id"
	// TaskIDKey 任务 ID
	TaskIDKey ContextKey = "task_id"
)

var (
	globalLogger *slog.Logger
	levelVar     *slog.LevelVar
)

// ContextHandler 装饰 slog.Handler，自动从 context.Context 中提取关键标识符
type ContextHandler struct {
	slog.Handler
}

// Handle 实现 slog.Handler 接口，注入上下文信息
func (h *ContextHandler) Handle(ctx context.Context, r slog.Record) error {
	if traceID, ok := ctx.Value(TraceIDKey).(string); ok {
		r.AddAttrs(slog.String("trace_id", traceID))
	}
	if nodeID, ok := ctx.Value(NodeIDKey).(string); ok {
		r.AddAttrs(slog.String("node_id", nodeID))
	}
	if taskID, ok := ctx.Value(TaskIDKey).(string); ok {
		r.AddAttrs(slog.String("task_id", taskID))
	}
	return h.Handler.Handle(ctx, r)
}

// Init 初始化全局日志
func Init(level string) error {
	levelVar = new(slog.LevelVar)
	if err := levelVar.UnmarshalText([]byte(level)); err != nil {
		levelVar.Set(slog.LevelInfo)
	}

	// 确保日志目录存在
	logDir := "logs"
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return err
	}

	// 配置 lumberjack 进行日志轮转
	fileWriter := &lumberjack.Logger{
		Filename:   filepath.Join(logDir, "luna-app.log"),
		MaxSize:    10, // megabytes
		MaxBackups: 5,
		MaxAge:     7, // days
		Compress:   true,
	}

	// 创建 JSON Handler
	opts := &slog.HandlerOptions{
		Level: levelVar,
	}
	
	// 同时输出到文件和标准输出
	// 在生产环境中，可能需要使用 io.MultiWriter(os.Stdout, fileWriter)
	// 这里为了简单，我们先只输出到标准输出，或者根据配置决定
	// 按照计划，我们需要写入文件并轮转
	
	// 使用 MultiWriter
	// 注意：slog 默认不支持 MultiWriter 直接输出不同格式，但我们可以将 JSON 输出到 MultiWriter
	// 为了更好的控制，我们直接将 JSON 输出到文件和控制台
	
	// 这里我们使用一个简单的 MultiWriter 包装
	// 但为了避免控制台输出 JSON 不易读，通常控制台用 TextHandler，文件用 JSONHandler
	// 计划中提到 "提供高性能的结构化 JSON 日志"，我们统一使用 JSONHandler
	
	// 暂时只输出到文件，如果需要控制台输出，可以使用 io.MultiWriter
	jsonHandler := slog.NewJSONHandler(fileWriter, opts)
	
	// 包装 ContextHandler
	contextHandler := &ContextHandler{Handler: jsonHandler}

	globalLogger = slog.New(contextHandler)
	slog.SetDefault(globalLogger)

	return nil
}

// SetLevel 动态调整日志级别
func SetLevel(level string) {
	if levelVar != nil {
		_ = levelVar.UnmarshalText([]byte(level))
	}
}

// Info 记录 Info 级别日志
func Info(ctx context.Context, msg string, args ...any) {
	if globalLogger != nil {
		globalLogger.InfoContext(ctx, msg, args...)
	}
}

// Warn 记录 Warn 级别日志
func Warn(ctx context.Context, msg string, args ...any) {
	if globalLogger != nil {
		globalLogger.WarnContext(ctx, msg, args...)
	}
}

// Error 记录 Error 级别日志
func Error(ctx context.Context, msg string, args ...any) {
	if globalLogger != nil {
		globalLogger.ErrorContext(ctx, msg, args...)
	}
}

// Debug 记录 Debug 级别日志
func Debug(ctx context.Context, msg string, args ...any) {
	if globalLogger != nil {
		globalLogger.DebugContext(ctx, msg, args...)
	}
}

