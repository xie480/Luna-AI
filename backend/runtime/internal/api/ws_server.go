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
	"luna-ai/backend/runtime/internal/memory"
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
	SessionID string        `json:"sessionId"`
	Message   string        `json:"message"`
	MsgID     string        `json:"msgId"`
	History   []ChatMessage `json:"history,omitempty"`
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

// InteractionQA 用于前端展示的单轮问答结构
// Phase 5 新增：存储在 Redis 中最近 3 轮 Q&A，用于右上角近期记忆面板展示
type InteractionQA struct {
	MsgID            string `json:"msgId"`
	UserContent      string `json:"userContent"`
	AssistantContent string `json:"assistantContent"`
	Timestamp        int64  `json:"timestamp"`
}

// InitStatePayload 定义前端 EVT_INIT_STATE 消息的 Payload
// Phase 5 精简：仅包含 sessionId 和 recentQA（最后 3 轮 Q&A），移除旧版的 messages/plan/memory
type InitStatePayload struct {
	SessionID string          `json:"sessionId"`
	RecentQA  []InteractionQA `json:"recentQA"`
}

// MemorySyncPayload 定义 EVT_MEMORY_SYNC 消息的 Payload
// Phase 6 新增：通知前端长期记忆已更新
type MemorySyncPayload struct {
	SessionID string `json:"sessionId"`
	MemoryID  string `json:"memoryId"`
	Status    string `json:"status"`
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
// Phase 6 新增：集成 memoryManager 用于记忆事件通知
type WSServer struct {
	aiClient      *AIClient
	redisRepo     *repository.ChatHistoryRedisRepo
	pgRepo        *repository.ChatHistoryPGRepo
	promptMgr     *prompt.Manager
	memoryManager *memory.Manager
	// 当前连接的 WebSocket 客户端列表
	clients   map[*WSConnection]bool
	clientsMu sync.RWMutex
}

// NewWSServer 创建一个新的 WSServer 实例
// Phase 6 新增 memoryManager 参数，用于注册记忆事件监听
func NewWSServer(aiClient *AIClient, redisRepo *repository.ChatHistoryRedisRepo, pgRepo *repository.ChatHistoryPGRepo, promptMgr *prompt.Manager, memoryManager *memory.Manager) *WSServer {
	server := &WSServer{
		aiClient:      aiClient,
		redisRepo:     redisRepo,
		pgRepo:        pgRepo,
		promptMgr:     promptMgr,
		memoryManager: memoryManager,
		clients:       make(map[*WSConnection]bool),
	}

	// 注册记忆事件监听
	if memoryManager != nil {
		memoryManager.OnEvent(func(event memory.MemoryEvent) {
			server.handleMemoryEvent(event)
		})
	}

	return server
}

// handleMemoryEvent 处理记忆系统事件，广播给所有连接的客户端
func (s *WSServer) handleMemoryEvent(event memory.MemoryEvent) {
	switch event.Type {
	case memory.EventMemorySync:
		payload, ok := event.Payload.(map[string]interface{})
		if !ok {
			return
		}

		sessionID, _ := payload["session_id"].(string)
		memoryID, _ := payload["memory_id"].(string)
		status, _ := payload["status"].(string)

		syncPayload := MemorySyncPayload{
			SessionID: sessionID,
			MemoryID:  memoryID,
			Status:    status,
		}

		payloadBytes, err := json.Marshal(syncPayload)
		if err != nil {
			logger.Error(context.Background(), "序列化 MemorySyncPayload 失败", "error", err)
			return
		}

		msg := WSMessage{
			Type:    types.WSMsgTypeEvtMemorySync,
			TraceID: snowflake.GenerateStringID(),
			Payload: payloadBytes,
		}

		// 广播给所有连接的客户端
		s.broadcast(msg)
	}
}

// broadcast 广播消息到所有连接的客户端
func (s *WSServer) broadcast(msg WSMessage) {
	s.clientsMu.RLock()
	defer s.clientsMu.RUnlock()

	for conn := range s.clients {
		if err := conn.WriteJSON(msg); err != nil {
			logger.Error(context.Background(), "广播消息失败", "error", err)
		}
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

	// 注册客户端
	s.clientsMu.Lock()
	s.clients[wsConn] = true
	s.clientsMu.Unlock()

	defer func() {
		s.clientsMu.Lock()
		delete(s.clients, wsConn)
		s.clientsMu.Unlock()
		wsConn.Close()
	}()

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
	case types.WSMsgTypeReqGetCalendarMetadata:
		s.handleGetCalendarMetadata(ctx, conn, msg)
	case types.WSMsgTypeReqGetChatHistory:
		s.handleGetChatHistory(ctx, conn, msg)
	default:
		logger.Warn(ctx, "未知的消息类型", zap.String("type", msg.Type))
		s.sendError(conn, msg.TraceID, 4001, "Unknown message type")
	}
}

// handleGetCalendarMetadata 处理获取日历元数据的请求
func (s *WSServer) handleGetCalendarMetadata(ctx context.Context, conn *WSConnection, msg WSMessage) {
	var reqPayload struct {
		YearMonth string `json:"year_month"`
	}
	if err := json.Unmarshal(msg.Payload, &reqPayload); err != nil || reqPayload.YearMonth == "" {
		logger.Error(ctx, "解析 REQ_GET_CALENDAR_METADATA Payload 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 4004, "Invalid REQ_GET_CALENDAR_METADATA payload")
		return
	}

	var activeDates []string
	var err error
	if s.pgRepo != nil {
		activeDates, err = s.pgRepo.GetActiveDatesByMonth(ctx, reqPayload.YearMonth)
		if err != nil {
			logger.Error(ctx, "从 PostgreSQL 获取活跃日期失败", zap.Error(err))
			s.sendError(conn, msg.TraceID, 5002, "Failed to fetch calendar metadata from database")
			return
		}
	} else {
		activeDates = []string{}
	}

	respPayload := struct {
		YearMonth   string   `json:"year_month"`
		ActiveDates []string `json:"active_dates"`
	}{
		YearMonth:   reqPayload.YearMonth,
		ActiveDates: activeDates,
	}

	payloadBytes, _ := json.Marshal(respPayload)
	respMsg := WSMessage{
		Type:    types.WSMsgTypeResCalendarMetadata,
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(respMsg); err != nil {
		logger.Error(ctx, "发送 RES_CALENDAR_METADATA 消息失败", zap.Error(err))
	}
}

// handleGetChatHistory 处理获取指定日期详细聊天记录的请求
func (s *WSServer) handleGetChatHistory(ctx context.Context, conn *WSConnection, msg WSMessage) {
	var reqPayload struct {
		Date string `json:"date"`
	}
	if err := json.Unmarshal(msg.Payload, &reqPayload); err != nil || reqPayload.Date == "" {
		logger.Error(ctx, "解析 REQ_GET_CHAT_HISTORY Payload 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 4005, "Invalid REQ_GET_CHAT_HISTORY payload")
		return
	}

	var interactions []repository.InteractionModel
	var err error
	if s.pgRepo != nil {
		interactions, err = s.pgRepo.GetInteractionsByDate(ctx, reqPayload.Date)
		if err != nil {
			logger.Error(ctx, "从 PostgreSQL 获取详细聊天记录失败", zap.Error(err))
			s.sendError(conn, msg.TraceID, 5003, "Failed to fetch chat history from database")
			return
		}
	}

	type FrontendChatMessage struct {
		ID        string `json:"id"`
		Role      string `json:"role"`
		Content   string `json:"content"`
		CreatedAt string `json:"created_at"`
	}

	var messages []FrontendChatMessage
	for _, interaction := range interactions {
		messages = append(messages, FrontendChatMessage{
			ID:        interaction.MessageID,
			Role:      types.RoleUser,
			Content:   interaction.UserContent,
			CreatedAt: interaction.CreatedAt.Format(time.RFC3339),
		})

		content := interaction.AssistantContent
		if interaction.Error != "" {
			content = interaction.Error
		}

		messages = append(messages, FrontendChatMessage{
			ID:        interaction.ID,
			Role:      types.RoleAssistant,
			Content:   content,
			CreatedAt: interaction.CreatedAt.Format(time.RFC3339),
		})
	}

	respPayload := struct {
		Date     string                `json:"date"`
		Messages []FrontendChatMessage `json:"messages"`
	}{
		Date:     reqPayload.Date,
		Messages: messages,
	}

	payloadBytes, _ := json.Marshal(respPayload)
	respMsg := WSMessage{
		Type:    types.WSMsgTypeResChatHistory,
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}

	if err := conn.WriteJSON(respMsg); err != nil {
		logger.Error(ctx, "发送 RES_CHAT_HISTORY 消息失败", zap.Error(err))
	}
}

// handleSyncInitState 处理前端初始状态同步请求
func (s *WSServer) handleSyncInitState(ctx context.Context, conn *WSConnection, msg WSMessage) {
	var reqPayload struct {
		SessionID string `json:"sessionId"`
	}
	sessionID := time.Now().Format("20060102")
	if err := json.Unmarshal(msg.Payload, &reqPayload); err == nil && reqPayload.SessionID != "" {
		sessionID = reqPayload.SessionID
	}

	var recentHistory []repository.Interaction
	if s.redisRepo != nil {
		_, recentHistory, _ = s.redisRepo.GetContext(ctx, sessionID)
	}

	startIndex := 0
	if len(recentHistory) > 3 {
		startIndex = len(recentHistory) - 3
	}
	last3History := recentHistory[startIndex:]

	recentQA := make([]InteractionQA, 0, len(last3History))
	for _, h := range last3History {
		recentQA = append(recentQA, InteractionQA{
			MsgID:            h.MsgID,
			UserContent:      h.UserContent,
			AssistantContent: h.AssistantContent,
			Timestamp:        h.Timestamp,
		})
	}

	payload := InitStatePayload{
		SessionID: sessionID,
		RecentQA:  recentQA,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		logger.Error(ctx, "序列化 InitStatePayload 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5000, "Internal server error")
		return
	}

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

	resp, err := s.aiClient.Ping(ctx, msg.TraceID)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 Ping 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5000, "AI service unavailable")
		return
	}

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

	var summary repository.ChatSummary
	var recentHistory []repository.Interaction
	if s.redisRepo != nil {
		var err error
		summary, recentHistory, err = s.redisRepo.GetContext(ctx, cmdPayload.SessionID)
		if err != nil {
			logger.Error(ctx, "从 Redis 获取上下文失败", zap.Error(err))
		}
	}

	protoHistory := make([]*pb.ChatMessage, 0, len(recentHistory)*2)
	for _, h := range recentHistory {
		protoHistory = append(protoHistory, &pb.ChatMessage{
			Role:    types.RoleUser,
			Content: h.UserContent,
		})
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

	currentTime := time.Now().Format("2006-01-02 15:04:05 Monday")
	promptVariables := map[string]string{
		"CURRENT_TIME":    currentTime,
		"CORE_SUMMARY":    summary.CoreSummary,
		"KEY_FACTS":       summary.KeyFacts,
		"MEMORY_SNIPPETS": memorySnippets,
	}

	// 1. 组装 Input Reconstruction Prompt
	var inputReconSystemPrompt, inputReconMemoryPrompt, inputReconRuntimePrompt string
	if s.promptMgr != nil {
		// 组装 Input Reconstruction 的三个槽位
		inputReconSystemPrompt, _ = s.promptMgr.AssemblePrompt(ctx, prompt.CategoryInputReconstruction, map[string]string{})

		inputReconMemoryPrompt, _ = s.promptMgr.AssemblePrompt(ctx, prompt.CategoryInputReconstruction, map[string]string{
			"CORE_SUMMARY":    summary.CoreSummary,
			"KEY_FACTS":       summary.KeyFacts,
			"MEMORY_SNIPPETS": memorySnippets,
		})

		// 动态注入枚举值
		primaryIntents := types.ValidPrimaryIntents()
		categories := types.ValidIntentCategories()
		dagRouteHints := types.ValidDagRouteHints()
		retrievalTypes := types.ValidRetrievalTypes()

		inputReconRuntimePrompt, _ = s.promptMgr.AssemblePrompt(ctx, prompt.CategoryInputReconstruction, map[string]string{
			"USER_INPUT":      cmdPayload.Message,
			"PRIMARY_INTENTS": `"` + strings.Join(primaryIntents, `", "`) + `"`,
			"CATEGORIES":      `"` + strings.Join(categories, `", "`) + `"`,
			"DAG_ROUTE_HINTS": `"` + strings.Join(dagRouteHints, `", "`) + `"`,
			"RETRIEVAL_TYPES": `"` + strings.Join(retrievalTypes, `", "`) + `"`,
		})
	}

	// 2. 调用 Input Reconstruction Agent
	reconReq := &pb.InputReconstructionRequest{
		TraceId:       msg.TraceID,
		UserInput:     cmdPayload.Message,
		SystemPrompt:  inputReconSystemPrompt,
		MemoryPrompt:  inputReconMemoryPrompt,
		RuntimePrompt: inputReconRuntimePrompt,
	}

	reconResp, err := s.aiClient.InputReconstruction(ctx, reconReq)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 InputReconstruction 失败", zap.Error(err))
		s.sendError(conn, msg.TraceID, 5001, "AI service input reconstruction failed")
		return
	}

	if !reconResp.Success {
		logger.Error(ctx, "InputReconstruction 失败", zap.String("error", reconResp.ErrorMessage))
		s.sendError(conn, msg.TraceID, 5001, "Input reconstruction failed: "+reconResp.ErrorMessage)
		return
	}

	// 3. 解析 Input Reconstruction 结果并组装 Chat Prompt
	var reconData struct {
		EmotionState struct {
			PrimaryEmotion string  `json:"primary_emotion"`
			Intensity      float64 `json:"intensity"`
			Valence        float64 `json:"valence"`
			Arousal        float64 `json:"arousal"`
			EmotionTrigger string  `json:"emotion_trigger"`
		} `json:"emotion_state"`
		Reconstruction struct {
			DisambiguatedText string `json:"disambiguated_text"`
		} `json:"reconstruction"`
	}

	if err := json.Unmarshal([]byte(reconResp.JsonOutput), &reconData); err != nil {
		logger.Error(ctx, "解析 InputReconstruction JSON 失败", zap.Error(err))
		// 降级处理：使用原始输入
		reconData.Reconstruction.DisambiguatedText = cmdPayload.Message
	}

	// 注入情绪特征
	promptVariables["EMOTION_PRIMARY"] = reconData.EmotionState.PrimaryEmotion
	promptVariables["EMOTION_INTENSITY"] = fmt.Sprintf("%.2f", reconData.EmotionState.Intensity)
	promptVariables["EMOTION_VALENCE"] = fmt.Sprintf("%.2f", reconData.EmotionState.Valence)
	promptVariables["EMOTION_AROUSAL"] = fmt.Sprintf("%.2f", reconData.EmotionState.Arousal)
	promptVariables["EMOTION_TRIGGER"] = reconData.EmotionState.EmotionTrigger

	var fullSystemPrompt string
	if s.promptMgr != nil {
		var err error
		fullSystemPrompt, err = s.promptMgr.AssemblePrompt(ctx, prompt.CategoryChat, promptVariables)
		if err != nil {
			logger.Error(ctx, "组装 Chat Prompt 失败", zap.Error(err))
		}
	}

	req := &pb.ChatRequest{
		TraceId:           msg.TraceID,
		Message:           cmdPayload.Message,
		History:           protoHistory,
		SystemPrompt:      fullSystemPrompt,
		DisambiguatedText: reconData.Reconstruction.DisambiguatedText,
	}

	logger.Info(ctx, "发送流式对话请求到 AI 服务", zap.String("trace_id", msg.TraceID))

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
	var streamError error

	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			logger.Error(ctx, "接收 ChatStream 响应失败", zap.Error(err))
			s.sendChatStreamError(conn, msg.TraceID, cmdPayload.MsgID, err.Error())
			streamError = err
			break
		}

		if isFirstChunk && resp.Chunk != "" {
			ttft := time.Since(startTime).Milliseconds()
			logger.Info(ctx, "首字延迟 (TTFT)", zap.String("trace_id", msg.TraceID), zap.Int64("ttft_ms", ttft))
			isFirstChunk = false
		}

		msgType := resp.Type
		if msgType == "" {
			msgType = "reply_chunk"
		}

		logger.Info(ctx, "接收 ChatStream 响应", zap.String("trace_id", msg.TraceID),
			zap.String("type", msgType), zap.String("chunk", resp.Chunk))

		switch msgType {
		case "reply_chunk":
			fullAssistantContent += resp.Chunk
		case "thought_content":
			fullAssistantThought += resp.Chunk
		case "emotion_update":
			fullAssistantEmotion = resp.Chunk
		default:
			logger.Warn(ctx, "收到未知的流式消息类型", zap.String("type", msgType), zap.String("trace_id", msg.TraceID))
			fullAssistantContent += resp.Chunk
		}

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

	// 异步持久化
	go func() {
		bgCtx := context.Background()
		now := time.Now()

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

		interaction := repository.Interaction{
			MsgID:            userMsgID,
			UserContent:      cmdPayload.Message,
			AssistantContent: fullAssistantContent,
			Thought:          fullAssistantThought,
			Emotion:          fullAssistantEmotion,
			Error:            errorJSON,
			Timestamp:        now.Unix(),
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

		if s.pgRepo != nil {
			if err := s.pgRepo.SaveInteraction(bgCtx, interactionModel); err != nil {
				logger.Error(bgCtx, "异步保存 Interaction 到 PG 失败", zap.Error(err))
			}
		}

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
func (s *WSServer) triggerCompression(ctx context.Context, sessionID string, traceID string) {
	logger.Info(ctx, "触发摘要压缩", zap.String("session_id", sessionID), zap.String("trace_id", traceID))

	summary, history, err := s.redisRepo.GetContext(ctx, sessionID)
	if err != nil {
		logger.Error(ctx, "获取上下文失败，无法进行压缩", zap.Error(err))
		return
	}

	if len(history) <= int(repository.MemWorkingWindowSize) {
		logger.Info(ctx, "历史记录未超过阈值，无需压缩",
			zap.Int("history_count", len(history)),
			zap.Int("threshold", int(repository.MemWorkingWindowSize)))
		return
	}

	compressCount := int(repository.MemCompressBatchSize)
	if len(history) < compressCount {
		compressCount = len(history)
	}

	logger.Info(ctx, "准备压缩历史记录",
		zap.Int("compress_count", compressCount),
		zap.Int("total_history", len(history)))

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

	summarizeVariables := map[string]string{
		"CURRENT_CORE_SUMMARY": summary.CoreSummary,
		"CURRENT_KEY_FACTS":    summary.KeyFacts,
		"MESSAGES_TEXT":        messagesText,
	}

	var fullSummarizePrompt string
	if s.promptMgr != nil {
		fullSummarizePrompt, err = s.promptMgr.AssemblePrompt(ctx, prompt.CategoryShortSummary, summarizeVariables)
		if err != nil {
			logger.Error(ctx, "组装 Summarize Prompt 失败", zap.Error(err))
		}
	}

	req := &pb.ShortSummarizeRequest{
		TraceId:         traceID,
		SummarizePrompt: fullSummarizePrompt,
	}

	resp, err := s.aiClient.ShortSummarize(ctx, req)
	if err != nil {
		logger.Error(ctx, "调用 AI 服务 ShortSummarize 失败", zap.Error(err))
		return
	}

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
