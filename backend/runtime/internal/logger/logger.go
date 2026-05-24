package logger

import (
	"context"
	"os"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

type contextKey string

const traceIDKey contextKey = "trace_id"

var globalLogger *zap.Logger

// Init 初始化全局日志
func Init(level string) error {
	var zapLevel zapcore.Level
	if err := zapLevel.UnmarshalText([]byte(level)); err != nil {
		zapLevel = zapcore.InfoLevel
	}

	encoderConfig := zap.NewProductionEncoderConfig()
	encoderConfig.TimeKey = "timestamp"
	encoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder

	core := zapcore.NewCore(
		zapcore.NewJSONEncoder(encoderConfig),
		zapcore.AddSync(os.Stdout),
		zapLevel,
	)

	globalLogger = zap.New(core, zap.AddCaller())
	return nil
}

// WithContext 返回带有 TraceID 的 Logger
func WithContext(ctx context.Context) *zap.Logger {
	if globalLogger == nil {
		// Fallback if not initialized
		globalLogger, _ = zap.NewProduction()
	}

	if ctx != nil {
		if traceID, ok := ctx.Value(traceIDKey).(string); ok {
			return globalLogger.With(zap.String("trace_id", traceID))
		}
	}
	return globalLogger
}

// Info 记录 Info 级别日志
func Info(ctx context.Context, msg string, fields ...zap.Field) {
	WithContext(ctx).Info(msg, fields...)
}

// Error 记录 Error 级别日志
func Error(ctx context.Context, msg string, fields ...zap.Field) {
	WithContext(ctx).Error(msg, fields...)
}

// Sync 刷新日志缓冲区
func Sync() {
	if globalLogger != nil {
		_ = globalLogger.Sync()
	}
}
