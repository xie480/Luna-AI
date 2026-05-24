package api

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/gorilla/websocket"
	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/logger"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	// 允许所有跨域请求，开发阶段方便调试
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// WSMessage 定义 WebSocket 消息结构
type WSMessage struct {
	Type    string          `json:"type"`
	TraceID string          `json:"trace_id"`
	Payload json.RawMessage `json:"payload"`
}

// PingPayload 定义 Ping 消息的 Payload
type PingPayload struct {
	Timestamp int64 `json:"timestamp"`
}

// PongPayload 定义 Pong 消息的 Payload
type PongPayload struct {
	Timestamp int64  `json:"timestamp"`
	Source    string `json:"source"`
}

// ErrorPayload 定义 Error 消息的 Payload
type ErrorPayload struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// WSServer 封装 WebSocket 服务
type WSServer struct {
	aiClient *AIClient
}

// NewWSServer 创建一个新的 WSServer 实例
func NewWSServer(aiClient *AIClient) *WSServer {
	return &WSServer{
		aiClient: aiClient,
	}
}

// HandleWS 处理 WebSocket 连接
func (s *WSServer) HandleWS(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		logger.Error(ctx, "升级 WebSocket 失败", zap.Error(err))
		return
	}
	defer conn.Close()

	logger.Info(ctx, "WebSocket 客户端已连接", zap.String("remote_addr", conn.RemoteAddr().String()))

	for {
		messageType, p, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				logger.Error(ctx, "读取 WebSocket 消息失败", zap.Error(err))
			} else {
				logger.Info(ctx, "WebSocket 客户端已断开连接")
			}
			break
		}

		if messageType != websocket.TextMessage {
			continue
		}

		var msg WSMessage
		if err := json.Unmarshal(p, &msg); err != nil {
			logger.Error(ctx, "解析 WebSocket 消息失败", zap.Error(err))
			s.sendError(conn, "", 4000, "Invalid JSON format")
			continue
		}

		s.handleMessage(ctx, conn, msg)
	}
}

func (s *WSServer) handleMessage(ctx context.Context, conn *websocket.Conn, msg WSMessage) {
	logger.Info(ctx, "收到 WebSocket 消息", zap.String("type", msg.Type), zap.String("trace_id", msg.TraceID))

	switch msg.Type {
	case "PING":
		s.handlePing(ctx, conn, msg)
	default:
		logger.Warn(ctx, "未知的消息类型", zap.String("type", msg.Type))
		s.sendError(conn, msg.TraceID, 4001, "Unknown message type")
	}
}

func (s *WSServer) handlePing(ctx context.Context, conn *websocket.Conn, msg WSMessage) {
	var payload PingPayload
	if err := json.Unmarshal(msg.Payload, &payload); err != nil {
		logger.Error(ctx, "解析 Ping Payload 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 4002, "Invalid Ping payload")
		return
	}

	// 转发给 AI 服务
	resp, err := s.aiClient.Ping(ctx, msg.TraceID)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 Ping 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5000, "AI service unavailable")
		return
	}

	// 构造 Pong 响应
	pongPayload := PongPayload{
		Timestamp: resp.Timestamp,
		Source:    resp.Source,
	}
	payloadBytes, _ := json.Marshal(pongPayload)

	pongMsg := WSMessage{
		Type:    "PONG",
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(pongMsg); err != nil {
		logger.Error(ctx, "发送 Pong 消息失败", zap.Error(err))
	}
}

func (s *WSServer) sendError(conn *websocket.Conn, traceID string, code int, message string) {
	errPayload := ErrorPayload{
		Code:    code,
		Message: message,
	}
	payloadBytes, _ := json.Marshal(errPayload)

	errMsg := WSMessage{
		Type:    "ERROR",
		TraceID: traceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(errMsg); err != nil {
		// 忽略发送错误消息时的错误
	}
}
