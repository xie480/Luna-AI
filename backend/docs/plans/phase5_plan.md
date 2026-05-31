# Phase 5: 短期会话记忆与上下文窗口管理实现方案 (后端)

## 1. 目标与设计理念

**目标**：
实现系统重启或前端刷新时的轻量级会话恢复。后端从 Redis 拉取当前会话（以日期为 SessionID）的最后 3 轮 Q&A 记录，并下发给前端，用于在 UI 右上角展示“近期记忆”面板。

**设计理念 (YAGNI)**：
- 放弃复杂的“任务状态”和“闲聊/任务隔离”预留字段，保持数据结构简单。
- 放弃全量历史记录的 UI 恢复，仅恢复最后 3 轮，保持界面清爽，符合拟人化陪伴定位。
- LLM 的上下文依然由后端在每次请求时全量注入，不受 UI 恢复策略影响。

## 2. 实施步骤

### 步骤 1：定义前后端通信协议 (Schema)

在 `backend/runtime/internal/api/ws_server.go` 中定义 `InitStatePayload` 结构体。

```go
// InitStatePayload 定义前端 EVT_INIT_STATE 消息的 Payload
type InitStatePayload struct {
	SessionID string        `json:"sessionId"`
	// 仅包含最后 3 轮的 Q&A 记录
	RecentQA  []InteractionQA `json:"recentQA"`
}

// InteractionQA 用于前端展示的单轮问答结构
type InteractionQA struct {
	MsgID            string `json:"msgId"`
	UserContent      string `json:"userContent"`
	AssistantContent string `json:"assistantContent"`
	Timestamp        int64  `json:"timestamp"`
}
```

### 步骤 2：实现 `handleSyncInitState` 逻辑

修改 `backend/runtime/internal/api/ws_server.go` 中的 `handleSyncInitState` 方法。

**逻辑流程**：
1. 解析前端发来的 `CMD_SYNC_INIT_STATE` 请求，获取 `SessionID`（前端应传入当天的日期字符串，如 "20250531"）。
2. 调用 `s.redisRepo.GetContext(ctx, sessionID)` 获取 `recentHistory`。
3. 截取 `recentHistory` 的最后 3 条记录。
4. 将这 3 条记录转换为 `InteractionQA` 结构。
5. 组装 `InitStatePayload` 并序列化为 JSON。
6. 通过 WebSocket 发送 `EVT_INIT_STATE` 消息给前端。

**代码草图**：

```go
func (s *WSServer) handleSyncInitState(ctx context.Context, conn *WSConnection, msg WSMessage) {
	var reqPayload struct {
		SessionID string `json:"sessionId"`
	}
	sessionID := time.Now().Format("20060102") // 默认使用当天日期
	if err := json.Unmarshal(msg.Payload, &reqPayload); err == nil && reqPayload.SessionID != "" {
		sessionID = reqPayload.SessionID
	}

	var recentHistory []repository.Interaction
	if s.redisRepo != nil {
		_, recentHistory, _ = s.redisRepo.GetContext(ctx, sessionID)
	}

	// 截取最后 3 条
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

	payloadBytes, _ := json.Marshal(payload)
	respMsg := WSMessage{
		Type:    types.WSMsgTypeEvtInitState,
		TraceID: msg.TraceID,
		Payload: payloadBytes,
	}
	_ = conn.WriteJSON(respMsg)
}
```

## 3. 总结

后端仅需提供一个极简的接口，将 Redis 中最新的 3 条记录下发，无需维护复杂的恢复状态机。这满足了前端展示“近期记忆”面板的需求。