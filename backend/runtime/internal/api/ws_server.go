package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/prompt"
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
	// Thought 字段存储助手消息的内心独白（thought），用于记忆系统展示历史心理状态
	// 仅 assistant 角色有此字段
	Thought string `json:"thought,omitempty"`
}

// CMDUserInputPayload 定义前端 CMD_USER_INPUT 消息的 Payload
// 前端发送的消息封装了会话 ID、消息 ID 等额外字段
type CMDUserInputPayload struct {
	SessionID    string        `json:"sessionId"`
	Message      string        `json:"message"`
	MsgID        string        `json:"msgId"`
	History      []ChatMessage `json:"history,omitempty"`
}

// ChatStreamPayload 定义 Chat 流式响应的 Payload
// type 字段区分消息来源："emotion_update"（情绪更新，用于 Live2D 表情同步）或 "reply_chunk"（回复文本片段）
type ChatStreamPayload struct {
	Type       string `json:"type"`
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
	promptMgr *prompt.Manager
}

// NewWSServer 创建一个新的 WSServer 实例
func NewWSServer(aiClient *AIClient, redisRepo *repository.ChatHistoryRedisRepo, pgRepo *repository.ChatHistoryPGRepo, promptMgr *prompt.Manager) *WSServer {
	return &WSServer{
		aiClient:  aiClient,
		redisRepo: redisRepo,
		pgRepo:    pgRepo,
		promptMgr: promptMgr,
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

	userMsgID := cmdPayload.MsgID
	if userMsgID == "" {
		userMsgID = snowflake.GenerateStringID()
	}

	// 1. 仅从 Redis 获取上下文 (摘要 + 历史 Interaction 列表)，此时不保存当前用户消息
	var summary repository.ChatSummary
	var recentHistory []repository.Interaction
	if s.redisRepo != nil {
		var err error
		summary, recentHistory, err = s.redisRepo.GetContext(ctx, cmdPayload.SessionID)
		if err != nil {
			logger.Error(ctx, "从 Redis 获取上下文失败", zap.Error(err))
		}
	}

	// 【第三步修复】将历史 Interaction 列表展开为 protobuf 的 ChatMessage 列表
	// 增加对失败回复的处理逻辑：如果助手历史回复存在错误状态，
	// 将该条错误信息正常封装入 protobuf 列表中，同时在相应字段中明确标记为回复失败状态并附带失败原因
	protoHistory := make([]*pb.ChatMessage, 0, len(recentHistory)*2)
	for _, h := range recentHistory {
		// 用户消息
		protoHistory = append(protoHistory, &pb.ChatMessage{
			Role:    types.RoleUser,
			Content: h.UserContent,
		})
		// 助手回复：无论是否出错，都将回复内容正常封装
		// 如果出错，通过 IsError 和 ErrorDetails 字段标记失败状态和原因
		assistantMsg := &pb.ChatMessage{
			Role:    types.RoleAssistant,
			Content: h.AssistantContent,
		}
		if h.Error != "" {
			assistantMsg.IsError = true
			assistantMsg.ErrorDetails = h.Error
		}
		protoHistory = append(protoHistory, assistantMsg)
	}

	// 【修复】将 history Interaction 列表格式化为文本，用于注入 MEMORY_SNIPPETS
	// 格式：每条 Interaction 包含用户消息和助手回复
	var memorySnippetsBuilder strings.Builder
	for i, h := range recentHistory {
		memorySnippetsBuilder.WriteString(fmt.Sprintf("[对话 %d]\n", i+1))
		memorySnippetsBuilder.WriteString(fmt.Sprintf("用户: %s\n", h.UserContent))
		if h.AssistantContent != "" {
			memorySnippetsBuilder.WriteString(fmt.Sprintf("Luna: %s\n", h.AssistantContent))
		}
		if h.Thought != "" {
			memorySnippetsBuilder.WriteString(fmt.Sprintf("(内心独白: %s)\n", h.Thought))
		}
		if h.Emotion != "" {
			memorySnippetsBuilder.WriteString(fmt.Sprintf("(心情: %s)\n", h.Emotion))
		}
		if h.Error != "" {
			memorySnippetsBuilder.WriteString(fmt.Sprintf("(错误: %s)\n", h.Error))
		}
		if h.Timestamp != 0 {
			timestamp := time.Unix(h.Timestamp, 0)
			memorySnippetsBuilder.WriteString(fmt.Sprintf("(时间: %s)\n", timestamp.Format("2006-01-02 15:04:05 Monday")))
		}
		memorySnippetsBuilder.WriteString("\n")
	}
	memorySnippets := memorySnippetsBuilder.String()

	// 组装完整的 System Prompt（由 Go 端通过缓存层完成全部渲染）
	currentTime := time.Now().Format("2006-01-02 15:04:05 Monday")
	promptVariables := map[string]string{
		"CURRENT_TIME":    currentTime,
		"CURRENT_MESSAGE": cmdPayload.Message,
		"CORE_SUMMARY":    summary.CoreSummary,
		"KEY_FACTS":       summary.KeyFacts,
		"MEMORY_SNIPPETS": memorySnippets,
	}

	var fullSystemPrompt string
	if s.promptMgr != nil {
		var err error
		fullSystemPrompt, err = s.promptMgr.AssemblePrompt(ctx, "chat", promptVariables)
		if err != nil {
			logger.Error(ctx, "组装 Chat Prompt 失败", zap.Error(err))
		}
	}

	// 构造 gRPC ChatRequest（已简化：由 Go 端直接传递完整 system_prompt）
	req := &pb.ChatRequest{
		TraceId:      msg.TraceID,
		Message:      cmdPayload.Message,
		History:      protoHistory,
		SystemPrompt: fullSystemPrompt,
	}

	logger.Info(ctx, "发送流式对话请求到 AI 服务", zap.String("trace_id", msg.TraceID))

	// 2. 调用 AI 服务的 ChatStream
	stream, err := s.aiClient.ChatStream(ctx, req)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 ChatStream 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5001, "AI service chat stream failed")
		return
	}

	startTime := time.Now()
	isFirstChunk := true
	var fullAssistantContent string
	var fullAssistantThought string
	var fullAssistantEmotion string
	// 【第二步优化】新增 streamError 变量捕获流式读取时产生的真实报错信息
	var streamError error

	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			logger.Error(ctx, "接收 ChatStream 响应失败", zap.Error(err))
			s.sendChatStreamError(conn, msg.TraceID, cmdPayload.MsgID, err.Error())
			// 【第二步优化】在 break 前捕获真实报错信息，传递到持久化协程
			streamError = err
			break
		}

		if isFirstChunk && resp.Chunk != "" {
			ttft := time.Since(startTime).Milliseconds()
			logger.Info(ctx, "首字延迟 (TTFT)", zap.String("trace_id", msg.TraceID), zap.Int64("ttft_ms", ttft))
			isFirstChunk = false
		}

		// 根据 gRPC 响应中的 type 字段进行不同的处理
		msgType := resp.Type
		if msgType == "" {
			msgType = "reply_chunk"
		}

		logger.Info(ctx, "接收 ChatStream 响应", zap.String("trace_id", msg.TraceID),
			zap.String("type", msgType), zap.String("chunk", resp.Chunk))

		// 根据消息类型进行不同的累积和转发逻辑
		// type 字段支持的值：
		//   - "reply_chunk"：正常的回复文本片段，累积到完整回复文本用于持久化
		//   - "thought_content"：内心独白文本片段，累积到完整 thought 用于持久化，不转发给前端
		//   - "emotion_update"：情绪更新消息，捕获情绪值用于持久化，仅用于 Live2D 表情同步
		switch msgType {
		case "reply_chunk":
			fullAssistantContent += resp.Chunk

		case "thought_content":
			fullAssistantThought += resp.Chunk
			// thought_content 不转发给前端（内心独白仅用于后端持久化）

		case "emotion_update":
			// 捕获情绪值用于持久化，实现宕机后情绪恢复
			fullAssistantEmotion = resp.Chunk

		default:
			// 未知消息类型，记录日志警告
			logger.Warn(ctx, "收到未知的流式消息类型", zap.String("type", msgType), zap.String("trace_id", msg.TraceID))
			// 仍按 reply_chunk 处理，避免丢失内容
			fullAssistantContent += resp.Chunk
		}

		// 转发给前端：仅转发 emotion_update 和 reply_chunk 类型，不转发 thought_content
		if msgType != "thought_content" {
			chatPayload := ChatStreamPayload{
				Type:       msgType,
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
				return
			}
		} else if resp.IsFinished {
			// 【问题1修复】thought_content 携带 is_finished=true 时，强制发送空结束信号
			// 防止前端收不到流结束事件，导致输入框持续 loading
			chatPayload := ChatStreamPayload{
				Type:       "reply_chunk",
				Chunk:      "",
				IsFinished: true,
				NodeID:     cmdPayload.MsgID,
				Error:      resp.Error,
			}
			payloadBytes, _ := json.Marshal(chatPayload)

			streamMsg := WSMessage{
				Type:    types.WSMsgTypeChatStream,
				TraceID: msg.TraceID,
				Payload: payloadBytes,
			}

			_ = conn.WriteJSON(streamMsg)
		}

		if resp.IsFinished {
			break
		}
	}

	// 3. 流式响应结束，开启异步协程执行持久化与压缩触发
	go func() {
		// 使用脱离原请求生命周期的 Background Context
		bgCtx := context.Background()
		now := time.Now()

		// 【第二步优化】动态捕获上层执行时产生的真实报错信息，替代写死的标准报错JSON
		// 由持久化协程负责动态序列化并写入包含真实 details 的报错 JSON
		errorJSON := ""
		if streamError != nil {
			errData := map[string]string{
				"error":   "generation_failed",
				"details": streamError.Error(),
			}
			errBytes, _ := json.Marshal(errData)
			errorJSON = string(errBytes)
			if fullAssistantContent == "" {
				fullAssistantContent = errorJSON
			}
		} else if fullAssistantContent == "" {
			errData := map[string]string{
				"error":   "generation_failed",
				"details": "Assistant returned empty content",
			}
			errBytes, _ := json.Marshal(errData)
			errorJSON = string(errBytes)
			fullAssistantContent = errorJSON
		}

		// 构造 Interaction 聚合实体（一问一答绑定为完整存储单元）
		interaction := repository.Interaction{
			MsgID:            userMsgID,
			UserContent:      cmdPayload.Message,
			AssistantContent: fullAssistantContent,
			Thought:          fullAssistantThought,
			// 【问题4修复】持久化情绪字段，确保宕机后能恢复情绪上下文
			Emotion:   fullAssistantEmotion,
			Error:     errorJSON,
			Timestamp: now.Unix(),
		}

		interactionModel := &repository.InteractionModel{
			ID:               snowflake.GenerateStringID(),
			SessionID:        cmdPayload.SessionID,
			MessageID:        userMsgID,
			UserContent:      cmdPayload.Message,
			AssistantContent: fullAssistantContent,
			Thought:          fullAssistantThought,
			Emotion:          fullAssistantEmotion,
			Error:            errorJSON,
			CreatedAt:        now,
		}

		// 异步写入 PG
		if s.pgRepo != nil {
			if err := s.pgRepo.SaveInteraction(bgCtx, interactionModel); err != nil {
				logger.Error(bgCtx, "异步保存 Interaction 到 PG 失败", zap.Error(err))
			}
		}

		// 异步写入 Redis 并触发压缩
		if s.redisRepo != nil {
			length, err := s.redisRepo.SaveInteraction(bgCtx, cmdPayload.SessionID, interaction)
			if err != nil {
				logger.Error(bgCtx, "异步保存 Interaction 到 Redis 失败", zap.Error(err))
			} else if length > int64(repository.MemWorkingWindowSize) {
				s.triggerCompression(bgCtx, cmdPayload.SessionID, msg.TraceID)
			}
		}
	}()
}

// triggerCompression 触发摘要压缩流程
// 做什么：提取最旧的 N 条历史记录，由 Go 组装完整的 summarize prompt，调用 AI 服务生成摘要，校验非空后更新 Redis
// 为什么这样做：确保摘要字段有效，防止空值覆盖 Redis 中的原有数据
// 输入输出：
//   - 输入：sessionID, traceID
//   - 输出：无（异步执行，结果通过日志记录）
// 边界条件：
//   - history 长度未超过阈值时不触发压缩
//   - AI 服务返回空字段时放弃本次更新
// 异常行为：
//   - 获取上下文失败时终止压缩
//   - AI 服务调用失败时终止压缩
func (s *WSServer) triggerCompression(ctx context.Context, sessionID string, traceID string) {
	logger.Info(ctx, "触发摘要压缩", zap.String("session_id", sessionID), zap.String("trace_id", traceID))

	// 获取当前上下文
	summary, history, err := s.redisRepo.GetContext(ctx, sessionID)
	if err != nil {
		logger.Error(ctx, "获取上下文失败，无法进行压缩", zap.Error(err))
		return
	}

	// 检查是否达到压缩阈值
	if len(history) <= int(repository.MemWorkingWindowSize) {
		logger.Info(ctx, "历史记录未超过阈值，无需压缩",
			zap.Int("history_count", len(history)),
			zap.Int("threshold", int(repository.MemWorkingWindowSize)))
		return
	}

	// 提取需要压缩的旧 Interaction 记录 (最旧的 N 条)
	compressCount := int(repository.MemCompressBatchSize)
	if len(history) < compressCount {
		compressCount = len(history)
	}

	logger.Info(ctx, "准备压缩历史记录",
		zap.Int("compress_count", compressCount),
		zap.Int("total_history", len(history)))

	// 将需要压缩的历史记录格式化为文本
	var messagesTextBuilder strings.Builder
	for i := 0; i < compressCount; i++ {
		interaction := history[i]
		messagesTextBuilder.WriteString(fmt.Sprintf("用户: %s\n", interaction.UserContent))
		messagesTextBuilder.WriteString(fmt.Sprintf("Luna: %s\n", interaction.AssistantContent))
		if interaction.Thought != "" {
			messagesTextBuilder.WriteString(fmt.Sprintf("(内心独白: %s)\n", interaction.Thought))
		}
		messagesTextBuilder.WriteString("\n")
	}
	messagesText := messagesTextBuilder.String()

	// 在 Go 端组装完整的 Summarize Prompt（通过缓存层获取各 slot 并注入占位符）
	summarizeVariables := map[string]string{
		"CURRENT_CORE_SUMMARY": summary.CoreSummary,
		"CURRENT_KEY_FACTS":    summary.KeyFacts,
		"MESSAGES_TEXT":        messagesText,
	}

	var fullSummarizePrompt string
	if s.promptMgr != nil {
		fullSummarizePrompt, err = s.promptMgr.AssemblePrompt(ctx, "summary", summarizeVariables)
		if err != nil {
			logger.Error(ctx, "组装 Summarize Prompt 失败", zap.Error(err))
		}
	}

	req := &pb.SummarizeContextRequest{
		TraceId:         traceID,
		SummarizePrompt: fullSummarizePrompt,
	}

	resp, err := s.aiClient.SummarizeContext(ctx, req)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 SummarizeContext 失败", zap.Error(err))
		return
	}

	// 【双重校验】Go 侧拦截：如果返回的摘要为空，则放弃本次更新，防止 Redis 被写空
	if strings.TrimSpace(resp.NewCoreSummary) == "" || strings.TrimSpace(resp.NewKeyFacts) == "" {
		logger.Warn(ctx, "AI 服务返回的摘要存在空字段，放弃本次更新",
			zap.String("session_id", sessionID),
			zap.Bool("core_summary_empty", strings.TrimSpace(resp.NewCoreSummary) == ""),
			zap.Bool("key_facts_empty", strings.TrimSpace(resp.NewKeyFacts) == ""))
		return
	}

	newSummary := repository.ChatSummary{
		CoreSummary: resp.NewCoreSummary,
		KeyFacts:    resp.NewKeyFacts,
	}

	// 更新 Redis 摘要并裁剪历史记录
	if err := s.redisRepo.UpdateSummaryAndTrim(ctx, sessionID, newSummary, int64(compressCount)); err != nil {
		logger.Error(ctx, "更新摘要并裁剪历史失败", zap.Error(err))
	} else {
		logger.Info(ctx, "摘要压缩完成",
			zap.String("session_id", sessionID),
			zap.Int("trimmed_count", compressCount))
	}
}

func (s *WSServer) sendChatStreamError(conn *WSConnection, traceID string, nodeID string, errorMsg string) {
	chatPayload := ChatStreamPayload{
		Type:       "reply_chunk",
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
