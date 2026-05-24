package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// AIClientInterface 定义 AI 客户端接口，用于测试模拟
type AIClientInterface interface {
	Ping(ctx context.Context, traceID string) (timestamp int64, source string, err error)
	Close() error
}

// MockAIClient 用于测试的模拟 AI 客户端
type MockAIClient struct {
	PingFunc func(ctx context.Context, traceID string) (timestamp int64, source string, err error)
}

func (m *MockAIClient) Ping(ctx context.Context, traceID string) (int64, string, error) {
	if m.PingFunc != nil {
		return m.PingFunc(ctx, traceID)
	}
	return time.Now().UnixMilli(), "mock-ai-service", nil
}

func (m *MockAIClient) Close() error {
	return nil
}

// TestWSMessageParsing 测试 WebSocket 消息解析
func TestWSMessageParsing(t *testing.T) {
	// 测试有效的 Ping 消息解析
	pingJSON := `{"type":"PING","trace_id":"test-123","payload":{"timestamp":1234567890}}`
	var msg WSMessage
	if err := json.Unmarshal([]byte(pingJSON), &msg); err != nil {
		t.Fatalf("解析 Ping 消息失败: %v", err)
	}

	if msg.Type != "PING" {
		t.Errorf("期望消息类型为 PING，实际为 %s", msg.Type)
	}

	if msg.TraceID != "test-123" {
		t.Errorf("期望 TraceID 为 test-123，实际为 %s", msg.TraceID)
	}

	// 解析 Payload
	var payload PingPayload
	if err := json.Unmarshal(msg.Payload, &payload); err != nil {
		t.Fatalf("解析 Ping Payload 失败: %v", err)
	}

	if payload.Timestamp != 1234567890 {
		t.Errorf("期望 Timestamp 为 1234567890，实际为 %d", payload.Timestamp)
	}
}

// TestPongPayloadSerialization 测试 Pong Payload 序列化
func TestPongPayloadSerialization(t *testing.T) {
	pongPayload := PongPayload{
		Timestamp: 1234567890,
		Source:    "test-source",
	}

	payloadBytes, err := json.Marshal(pongPayload)
	if err != nil {
		t.Fatalf("序列化 Pong Payload 失败: %v", err)
	}

	var parsed PongPayload
	if err := json.Unmarshal(payloadBytes, &parsed); err != nil {
		t.Fatalf("反序列化 Pong Payload 失败: %v", err)
	}

	if parsed.Timestamp != pongPayload.Timestamp {
		t.Errorf("期望 Timestamp 为 %d，实际为 %d", pongPayload.Timestamp, parsed.Timestamp)
	}

	if parsed.Source != pongPayload.Source {
		t.Errorf("期望 Source 为 %s，实际为 %s", pongPayload.Source, parsed.Source)
	}
}

// TestErrorPayloadSerialization 测试 Error Payload 序列化
func TestErrorPayloadSerialization(t *testing.T) {
	errPayload := ErrorPayload{
		Code:    4000,
		Message: "Invalid JSON format",
	}

	payloadBytes, err := json.Marshal(errPayload)
	if err != nil {
		t.Fatalf("序列化 Error Payload 失败: %v", err)
	}

	var parsed ErrorPayload
	if err := json.Unmarshal(payloadBytes, &parsed); err != nil {
		t.Fatalf("反序列化 Error Payload 失败: %v", err)
	}

	if parsed.Code != errPayload.Code {
		t.Errorf("期望 Code 为 %d，实际为 %d", errPayload.Code, parsed.Code)
	}

	if parsed.Message != errPayload.Message {
		t.Errorf("期望 Message 为 %s，实际为 %s", errPayload.Message, parsed.Message)
	}
}

// TestWebSocketConnection 测试 WebSocket 连接建立
func TestWebSocketConnection(t *testing.T) {
	// 创建一个简单的 WebSocket 处理器
	handler := func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		// 读取消息并回显
		for {
			messageType, p, err := conn.ReadMessage()
			if err != nil {
				break
			}
			if err := conn.WriteMessage(messageType, p); err != nil {
				break
			}
		}
	}

	// 创建测试服务器
	server := httptest.NewServer(http.HandlerFunc(handler))
	defer server.Close()

	// 将 HTTP URL 转换为 WebSocket URL
	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")

	// 连接 WebSocket
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("连接 WebSocket 失败: %v", err)
	}
	defer conn.Close()

	// 发送测试消息
	testMsg := "test-message"
	if err := conn.WriteMessage(websocket.TextMessage, []byte(testMsg)); err != nil {
		t.Fatalf("发送消息失败: %v", err)
	}

	// 接收回显消息
	_, received, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("接收消息失败: %v", err)
	}

	if string(received) != testMsg {
		t.Errorf("期望收到 %s，实际收到 %s", testMsg, string(received))
	}
}