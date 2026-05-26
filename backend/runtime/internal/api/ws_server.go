package api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/types"
	pb "luna-ai/backend/runtime/shared/proto"
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

// ChatMessage 定义单条对话消息（与前端 types.ts 中的 ChatMessage 对齐）
type ChatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatRequestPayload 定义 Chat 请求的 Payload（增强版，支持历史记录和系统提示词）
type ChatRequestPayload struct {
	Message      string         `json:"message"`
	History      []ChatMessage  `json:"history,omitempty"`
	SystemPrompt string         `json:"system_prompt,omitempty"`
}

// CMDUserInputPayload 定义前端 CMD_USER_INPUT 消息的 Payload
// 前端发送的消息封装了会话 ID、消息 ID 等额外字段
type CMDUserInputPayload struct {
	SessionID    string         `json:"sessionId"`
	Message      string         `json:"message"`
	MsgID        string         `json:"msgId"`
	History      []ChatMessage  `json:"history,omitempty"`
	SystemPrompt string         `json:"system_prompt,omitempty"`
}

// ChatStreamPayload 定义 Chat 流式响应的 Payload
type ChatStreamPayload struct {
	Chunk      string `json:"chunk"`
	IsFinished bool   `json:"is_finished"`
	NodeID     string `json:"node_id"`
	Error      string `json:"error,omitempty"`
}

// WSConnection 封装 websocket.Conn，提供并发安全的写操作
type WSConnection struct {
	conn *websocket.Conn
	mu   sync.Mutex
}

// WriteJSON 并发安全地写入 JSON 数据
func (c *WSConnection) WriteJSON(v interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.conn.WriteJSON(v)
}

// Close 关闭连接
func (c *WSConnection) Close() error {
	return c.conn.Close()
}

// RemoteAddr 获取远程地址
func (c *WSConnection) RemoteAddr() string {
	return c.conn.RemoteAddr().String()
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
	wsConn := &WSConnection{conn: conn}
	defer wsConn.Close()

	logger.Info(ctx, "WebSocket 客户端已连接", zap.String("remote_addr", wsConn.RemoteAddr()))

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
			s.sendError(wsConn, "", 4000, "Invalid JSON format")
			continue
		}

		s.handleMessage(ctx, wsConn, msg)
	}
}

func (s *WSServer) handleMessage(ctx context.Context, conn *WSConnection, msg WSMessage) {
	logger.Info(ctx, "收到 WebSocket 消息", zap.String("type", msg.Type), zap.String("trace_id", msg.TraceID))

	switch msg.Type {
	case types.WSMsgTypePing:
		s.handlePing(ctx, conn, msg)
	case types.WSMsgTypeChatRequest, types.WSMsgTypeCmdUserInput:
		// 支持两种消息类型路由到聊天处理：
		//   CHAT_REQUEST: 直接聊天请求
		//   CMD_USER_INPUT: 前端携带 sessionId/msgId 的聊天请求
		// 异步处理聊天请求，避免阻塞读循环
		go s.handleChatRequest(ctx, conn, msg)
	case types.WSMsgTypeCmdSyncInitState:
		s.handleSyncInitState(ctx, conn, msg)
	default:
		logger.Warn(ctx, "未知的消息类型", zap.String("type", msg.Type))
		s.sendError(conn, msg.TraceID, 4001, "Unknown message type")
	}
}

func (s *WSServer) handleSyncInitState(ctx context.Context, conn *WSConnection, msg WSMessage) {
	// 构造初始状态响应
	// 暂时返回一个空的初始状态
	payloadBytes := []byte(`{"sessionId": "default-session", "messages": [], "activePlan": null, "memory": null}`)

	respMsg := WSMessage{
		Type:    types.WSMsgTypeEvtInitState,
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(respMsg); err != nil {
		logger.Error(ctx, "发送 EVT_INIT_STATE 消息失败", zap.Error(err))
	}
}

func (s *WSServer) handlePing(ctx context.Context, conn *WSConnection, msg WSMessage) {
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
		Type:    types.WSMsgTypePong,
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(pongMsg); err != nil {
		logger.Error(ctx, "发送 Pong 消息失败", zap.Error(err))
	}
}

func (s *WSServer) handleChatRequest(ctx context.Context, conn *WSConnection, msg WSMessage) {
	// 提取聊天请求参数，兼容 CHAT_REQUEST 和 CMD_USER_INPUT 两种消息类型
	var message string
	var history []ChatMessage
	var systemPrompt string
	var nodeID string

	if msg.Type == types.WSMsgTypeCmdUserInput {
		// 解析 CMD_USER_INPUT 格式（前端实际发送的格式）
		var cmdPayload CMDUserInputPayload
		if err := json.Unmarshal(msg.Payload, &cmdPayload); err != nil {
			logger.Error(ctx, "解析 CMD_USER_INPUT Payload 失败", zap.Error(err))
			s.sendError(conn, msg.TraceID, 4003, "Invalid CMD_USER_INPUT payload")
			return
		}
		message = cmdPayload.Message
		history = cmdPayload.History
		systemPrompt = cmdPayload.SystemPrompt
		nodeID = cmdPayload.MsgID
	} else {
		// 解析 CHAT_REQUEST 格式
		var payload ChatRequestPayload
		if err := json.Unmarshal(msg.Payload, &payload); err != nil {
			logger.Error(ctx, "解析 ChatRequest Payload 失败", zap.Error(err))
			s.sendError(conn, msg.TraceID, 4003, "Invalid ChatRequest payload")
			return
		}
		message = payload.Message
		history = payload.History
		systemPrompt = payload.SystemPrompt
		nodeID = "node-" + msg.TraceID
	}

	// 将前端的历史消息（ChatMessage）转换为 protobuf 的 ChatMessage
	protoHistory := make([]*pb.ChatMessage, 0, len(history))
	for _, h := range history {
		protoHistory = append(protoHistory, &pb.ChatMessage{
			Role:    h.Role,
			Content: h.Content,
		})
	}

	// 构造 gRPC ChatRequest，包含历史记录和系统提示词
	req := &pb.ChatRequest{
		TraceId:      msg.TraceID,
		Message:      message,
		History:      protoHistory,
		SystemPrompt: systemPrompt,
	}

	historyCount := len(protoHistory)
	logger.Info(ctx, "发送流式对话请求到 AI 服务",
		zap.String("trace_id", msg.TraceID),
		zap.Int("history_count", historyCount),
		zap.Bool("has_custom_prompt", systemPrompt != ""),
	)

	// 调用 AI 服务的 ChatStream
	stream, err := s.aiClient.ChatStream(ctx, req)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 ChatStream 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5001, "AI service chat stream failed")
		return
	}

	startTime := time.Now()
	isFirstChunk := true

	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			// 流正常结束
			break
		}
		if err != nil {
			logger.Error(ctx, "接收 ChatStream 响应失败", zap.Error(err))
			s.sendChatStreamError(conn, msg.TraceID, nodeID, err.Error())
			return
		}

		if isFirstChunk && resp.Chunk != "" {
			ttft := time.Since(startTime).Milliseconds()
			logger.Info(ctx, "首字延迟 (TTFT)",
				zap.String("trace_id", msg.TraceID),
				zap.Int64("ttft_ms", ttft),
			)
			isFirstChunk = false
		}

		chatPayload := ChatStreamPayload{
			Chunk:      resp.Chunk,
			IsFinished: resp.IsFinished,
			NodeID:     nodeID,
			Error:      resp.Error,
		}
		payloadBytes, _ := json.Marshal(chatPayload)

		streamMsg := WSMessage{
			Type:    types.WSMsgTypeChatStream,
			TraceID: msg.TraceID,
			Payload: payloadBytes,
		}

		if err := conn.WriteJSON(streamMsg); err != nil {
			logger.Error(ctx, "发送 CHAT_STREAM 消息失败", zap.Error(err))
			// 如果发送失败（例如连接已断开），则退出循环
			return
		}

		if resp.IsFinished {
			break
		}
	}
}

func (s *WSServer) sendChatStreamError(conn *WSConnection, traceID string, nodeID string, errorMsg string) {
	chatPayload := ChatStreamPayload{
		Chunk:      "",
		IsFinished: true,
		NodeID:     nodeID,
		Error:      errorMsg,
	}
	payloadBytes, _ := json.Marshal(chatPayload)

	streamMsg := WSMessage{
		Type:    types.WSMsgTypeChatStream,
		TraceID: traceID,
		Payload: payloadBytes,
	}

	_ = conn.WriteJSON(streamMsg)
}

func (s *WSServer) sendError(conn *WSConnection, traceID string, code int, message string) {
	errPayload := ErrorPayload{
		Code:    code,
		Message: message,
	}
	payloadBytes, _ := json.Marshal(errPayload)

	errMsg := WSMessage{
		Type:    types.WSMsgTypeError,
		TraceID: traceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(errMsg); err != nil {
		// 忽略发送错误消息时的错误
	}
}
