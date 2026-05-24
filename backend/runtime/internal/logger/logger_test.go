package logger

import (
	"bytes"
	"context"
	"encoding/json"
	"testing"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// TestLoggerFormatAndTraceID 测试日志格式和 TraceID 注入
// 做什么：验证日志输出是否为 JSON 格式，且包含正确的 trace_id 字段。
// 为什么这样做：确保全链路追踪的 TraceID 能够正确落盘，满足可观测性要求。
// 输入输出：输入带有 trace_id 的 context，输出捕获的日志字节流。
// 边界条件：context 中没有 trace_id 时，不应抛出异常，且日志中不应有 trace_id 字段。
// 异常行为：如果 JSON 解析失败，测试将报错。
func TestLoggerFormatAndTraceID(t *testing.T) {
	// 1. 替换全局 logger 的输出目标为 buffer
	var buf bytes.Buffer
	encoderConfig := zap.NewProductionEncoderConfig()
	encoderConfig.TimeKey = "timestamp"
	encoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder

	core := zapcore.NewCore(
		zapcore.NewJSONEncoder(encoderConfig),
		zapcore.AddSync(&buf),
		zapcore.InfoLevel,
	)
	globalLogger = zap.New(core)

	// 2. 创建带有 trace_id 的 context
	ctx := context.WithValue(context.Background(), traceIDKey, "test-trace-123")

	// 3. 记录日志
	Info(ctx, "test message", zap.String("extra", "value"))

	// 4. 解析输出的 JSON
	var logOutput map[string]interface{}
	if err := json.Unmarshal(buf.Bytes(), &logOutput); err != nil {
		t.Fatalf("Failed to parse log output as JSON: %v", err)
	}

	// 5. 验证字段
	if logOutput["msg"] != "test message" {
		t.Errorf("Expected msg 'test message', got '%v'", logOutput["msg"])
	}
	if logOutput["trace_id"] != "test-trace-123" {
		t.Errorf("Expected trace_id 'test-trace-123', got '%v'", logOutput["trace_id"])
	}
	if logOutput["extra"] != "value" {
		t.Errorf("Expected extra 'value', got '%v'", logOutput["extra"])
	}
}
