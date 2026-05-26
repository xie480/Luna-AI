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
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/types"
	"luna-ai/backend/runtime/internal/utils/snowflake"
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
	aiClient  *AIClient
	redisRepo *repository.ChatHistoryRedisRepo
	pgRepo    *repository.ChatHistoryPGRepo
}

// NewWSServer 创建一个新的 WSServer 实例
func NewWSServer(aiClient *AIClient, redisRepo *repository.ChatHistoryRedisRepo, pgRepo *repository.ChatHistoryPGRepo) *WSServer {
	return &WSServer{
		aiClient:  aiClient,
		redisRepo: redisRepo,
		pgRepo:    pgRepo,
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
	case types.WSMsgTypeCmdUserInput:
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
	var cmdPayload CMDUserInputPayload
	if err := json.Unmarshal(msg.Payload, &cmdPayload); err != nil {
		logger.Error(ctx, "解析 CMD_USER_INPUT Payload 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 4003, "Invalid CMD_USER_INPUT payload")
		return
	}

	// 1. 保存用户消息到 PG 和 Redis
	userMsgID := cmdPayload.MsgID
	if userMsgID == "" {
		userMsgID = snowflake.GenerateStringID()
	}
	now := time.Now()
	
	userMsg := repository.ChatMessage{
		MsgID:     userMsgID,
		Role:      "user",
		Content:   cmdPayload.Message,
		Timestamp: now.Unix(),
	}
	
	userMsgModel := &repository.ChatMessageModel{
		ID:        snowflake.GenerateStringID(),
		SessionID: cmdPayload.SessionID,
		MsgID:     userMsgID,
		Role:      "user",
		Content:   cmdPayload.Message,
		CreatedAt: now,
	}

	if s.pgRepo != nil {
		if err := s.pgRepo.SaveMessage(ctx, userMsgModel); err != nil {
			logger.Error(ctx, "保存用户消息到 PG 失败", zap.Error(err))
		}
	}

	if s.redisRepo != nil {
		if _, err := s.redisRepo.SaveMessage(ctx, cmdPayload.SessionID, userMsg); err != nil {
			logger.Error(ctx, "保存用户消息到 Redis 失败", zap.Error(err))
		}
	}

	// 2. 从 Redis 获取上下文 (摘要 + 近期历史)
	var summary repository.ChatSummary
	var recentHistory []repository.ChatMessage
	if s.redisRepo != nil {
		var err error
		summary, recentHistory, err = s.redisRepo.GetContext(ctx, cmdPayload.SessionID)
		if err != nil {
			logger.Error(ctx, "从 Redis 获取上下文失败", zap.Error(err))
		}
	}

	// 将近期历史转换为 protobuf 的 ChatMessage
	protoHistory := make([]*pb.ChatMessage, 0, len(recentHistory))
	for _, h := range recentHistory {
		// 排除当前消息，因为当前消息已经在 req.Message 中
		if h.MsgID != userMsgID {
			protoHistory = append(protoHistory, &pb.ChatMessage{
				Role:    h.Role,
				Content: h.Content,
			})
		}
	}

	// 构造 gRPC ChatRequest，包含历史记录、系统提示词和摘要
	req := &pb.ChatRequest{
		TraceId:      msg.TraceID,
		Message:      cmdPayload.Message,
		History:      protoHistory,
		SystemPrompt: cmdPayload.SystemPrompt,
		CoreSummary:  summary.CoreSummary,
		KeyFacts:     summary.KeyFacts,
	}

	historyCount := len(protoHistory)
	logger.Info(ctx, "发送流式对话请求到 AI 服务",
		zap.String("trace_id", msg.TraceID),
		zap.Int("history_count", historyCount),
		zap.Bool("has_custom_prompt", cmdPayload.SystemPrompt != ""),
		zap.Bool("has_summary", summary.CoreSummary != ""),
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
	var fullAssistantContent string

	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			// 流正常结束
			break
		}
		if err != nil {
			logger.Error(ctx, "接收 ChatStream 响应失败", zap.Error(err))
			s.sendChatStreamError(conn, msg.TraceID, cmdPayload.MsgID, err.Error())
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

		fullAssistantContent += resp.Chunk

		chatPayload := ChatStreamPayload{
			Chunk:      resp.Chunk,
			IsFinished: resp.IsFinished,
			NodeID:     cmdPayload.MsgID,
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

	// 3. 流式响应结束，保存 Assistant 消息到 PG 和 Redis
	if fullAssistantContent != "" {
		assistantMsgID := snowflake.GenerateStringID()
		assistantNow := time.Now()

		assistantMsg := repository.ChatMessage{
			MsgID:     assistantMsgID,
			Role:      "assistant",
			Content:   fullAssistantContent,
			Timestamp: assistantNow.Unix(),
		}

		assistantMsgModel := &repository.ChatMessageModel{
			ID:        snowflake.GenerateStringID(),
			SessionID: cmdPayload.SessionID,
			MsgID:     assistantMsgID,
			Role:      "assistant",
			Content:   fullAssistantContent,
			CreatedAt: assistantNow,
		}

		if s.pgRepo != nil {
			if err := s.pgRepo.SaveMessage(context.Background(), assistantMsgModel); err != nil {
				logger.Error(context.Background(), "保存 Assistant 消息到 PG 失败", zap.Error(err))
			}
		}

		if s.redisRepo != nil {
			length, err := s.redisRepo.SaveMessage(context.Background(), cmdPayload.SessionID, assistantMsg)
			if err != nil {
				logger.Error(context.Background(), "保存 Assistant 消息到 Redis 失败", zap.Error(err))
			} else if length > repository.MemWorkingWindowSize {
				// 4. 触发摘要压缩
				go s.triggerCompression(context.Background(), cmdPayload.SessionID, msg.TraceID)
			}
		}
	}
}

func (s *WSServer) triggerCompression(ctx context.Context, sessionID string, traceID string) {
	logger.Info(ctx, "触发摘要压缩", zap.String("session_id", sessionID), zap.String("trace_id", traceID))

	// 获取当前上下文
	summary, history, err := s.redisRepo.GetContext(ctx, sessionID)
	if err != nil {
		logger.Error(ctx, "获取上下文失败，无法进行压缩", zap.Error(err))
		return
	}

	if len(history) <= repository.MemWorkingWindowSize {
		return
	}

	// 提取需要压缩的旧消息
	compressCount := repository.MemCompressBatchSize
	if len(history) < compressCount {
		compressCount = len(history)
	}

	messagesToCompress := make([]*pb.ChatMessage, 0, compressCount)
	for i := 0; i < compressCount; i++ {
		messagesToCompress = append(messagesToCompress, &pb.ChatMessage{
			Role:    history[i].Role,
			Content: history[i].Content,
		})
	}

	req := &pb.SummarizeContextRequest{
		TraceId:              traceID,
		CurrentCoreSummary:   summary.CoreSummary,
		CurrentKeyFacts:      summary.KeyFacts,
		MessagesToCompress:   messagesToCompress,
	}

	resp, err := s.aiClient.SummarizeContext(ctx, req)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 SummarizeContext 失败", zap.Error(err))
		return
	}

	newSummary := repository.ChatSummary{
		CoreSummary: resp.NewCoreSummary,
		KeyFacts:    resp.NewKeyFacts,
	}

	if err := s.redisRepo.UpdateSummaryAndTrim(ctx, sessionID, newSummary, int64(compressCount)); err != nil {
		logger.Error(ctx, "更新摘要并裁剪历史失败", zap.Error(err))
	} else {
		logger.Info(ctx, "摘要压缩完成", zap.String("session_id", sessionID))
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
