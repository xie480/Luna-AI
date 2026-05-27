# 核心问题修复与架构调整方案

本文档针对当前系统在前后端交互、渲染逻辑及存储设计上的五个核心问题，提供完整的代码修改方案与架构调整逻辑。

## 1. 修复流式输出结束后前端输入框加载状态无法取消的问题

### 问题分析
当前 `ws_server.go` 在接收到 gRPC 的流式响应时，如果 `msgType == "thought_content"`，会跳过向前端转发。如果 LLM 返回的最后一个 chunk 是 `thought_content` 且携带了 `is_finished=true` 信号，该结束信号会被 Go 侧静默吞掉，导致前端永远收不到流结束事件，输入框持续处于 `isWaiting` 状态。

### 修改方案
**文件**：`backend/runtime/internal/api/ws_server.go`
**逻辑**：
在 `handleChatRequest` 方法中，处理 gRPC 响应的循环内，独立处理 `resp.IsFinished` 信号。即使当前 chunk 是 `thought_content`，只要 `IsFinished` 为 `true`，就必须向前端发送一个空的 `reply_chunk` 消息以传递结束状态。

```go
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
    // 强制发送结束信号，防止前端一直 loading
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
```

## 2. 优化后端文本分块的处理规则

### 问题分析
前端气泡渲染需要语义完整的句子，但不需要句末的逗号和句号，同时需要保留表达语气的标点（如 `!`、`?`、`~`、`...`）。

### 修改方案
**文件**：`backend/ai-service/app/llm/stream_parser.py`
**逻辑**：
在 `_pop_sentence` 和 `flush` 方法中，引入正则替换逻辑 `re.sub(r'[。，,\.]+$', '', sentence)`。在切分出 `sentence` 后，先执行 `strip()`，然后应用正则精准剔除末尾的平白标点，再封装为 `reply_chunk` 投递。

```python
import re

def _pop_sentence(self) -> List[Tuple[str, str]]:
    msgs: List[Tuple[str, str]] = []
    while True:
        m = _SENTENCE_BOUNDARY_RE.search(self._reply_buffer)
        if not m:
            break
        idx = m.end()
        sentence = self._reply_buffer[:idx]
        self._reply_buffer = self._reply_buffer[idx:]
        
        # 标点过滤逻辑
        sentence = sentence.strip()
        sentence = re.sub(r'[。，,\.]+$', '', sentence)
        if sentence:
            msgs.append(("reply_chunk", sentence))
    return msgs

def flush(self) -> List[Tuple[str, str]]:
    msgs: List[Tuple[str, str]] = []
    msgs.extend(self._emit_thought())
    if self._reply_buffer:
        sentence = self._reply_buffer.strip()
        sentence = re.sub(r'[。，,\.]+$', '', sentence)
        if sentence:
            msgs.append(("reply_chunk", sentence))
        self._reply_buffer = ""
    return msgs
```

## 3. 重构前端气泡渲染的队列控制机制

### 问题分析
当前 `BubbleStack.tsx` 监听到 `luna:show-bubble` 事件后直接渲染，如果后端下发过快，会导致满屏气泡重叠，且停留时间计算不够平滑。

### 修改方案
**文件**：`frontend/src/renderer/hooks/useBubble.ts`
**逻辑**：
引入内部缓冲队列 `queueRef` 和当前展示气泡计数 `activeCountRef`。限制最大同时展示数量为 3。动态计算停留时间：`Math.max(3000, text.length * 250)`。

```typescript
import { useState, useRef, useCallback } from 'react';
import gsap from 'gsap';

export interface Bubble {
  id: number;
  text: string;
  leaving: boolean;
}

interface QueueItem {
  id: number;
  text: string;
  duration: number;
}

export const useBubble = () => {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const bubbleElsRef = useRef<Map<number, HTMLDivElement>>(new Map());
  const bubbleIdCounter = useRef(0);
  
  const queueRef = useRef<QueueItem[]>([]);
  const activeCountRef = useRef(0);
  const MAX_BUBBLES = 3;

  const registerBubble = useCallback((el: HTMLDivElement | null, id: number) => {
    if (!el) {
      bubbleElsRef.current.delete(id);
      return;
    }
    bubbleElsRef.current.set(id, el);
  }, []);

  const processQueue = useCallback(() => {
    if (activeCountRef.current >= MAX_BUBBLES || queueRef.current.length === 0) {
      return;
    }

    const item = queueRef.current.shift()!;
    activeCountRef.current++;

    const { id, text, duration } = item;

    const prevPositions = new Map<number, number>();
    bubbleElsRef.current.forEach((el, key) => {
      try { prevPositions.set(key, el.getBoundingClientRect().top); } catch (e) {}
    });

    setBubbles(prev => [...prev, { id, text, leaving: false }]);

    requestAnimationFrame(() => {
      bubbleElsRef.current.forEach((el, key) => {
        if (prevPositions.has(key) && key !== id) {
          const prevTop = prevPositions.get(key)!;
          const currentTop = el.getBoundingClientRect().top;
          const dy = prevTop - currentTop;
          if (Math.abs(dy) > 0.5) {
            gsap.fromTo(el, { y: dy }, { y: 0, duration: 0.3, ease: "power2.out" });
          }
        }
      });
    });

    setTimeout(() => {
      setBubbles(prev => prev.map(b => b.id === id ? { ...b, leaving: true } : b));
      setTimeout(() => {
        setBubbles(prev => prev.filter(b => b.id !== id));
        bubbleElsRef.current.delete(id);
        activeCountRef.current--;
        processQueue(); // 销毁后尝试处理下一个
      }, 300);
    }, duration);
  }, []);

  const showBubble = useCallback((text: string, duration?: number) => {
    const id = bubbleIdCounter.current++;
    // 动态计算停留时间：基础 3000ms，每字 250ms
    const calcDuration = duration ?? Math.max(3000, text.length * 250);
    queueRef.current.push({ id, text, duration: calcDuration });
    processQueue();
  }, [processQueue]);

  return { bubbles, showBubble, registerBubble };
};
```

## 4. 升级数据持久化模型以支持状态恢复

### 问题分析
当前 `ChatMessageModel` 和 Redis 的 `ChatMessage` 结构中缺少 `Emotion` 字段，导致重启后无法恢复角色的情绪上下文。

### 修改方案
**文件**：`backend/runtime/internal/repository/models.go` & `chat_history_redis.go`
**逻辑**：
在模型中显式增加 `Emotion` 字段。在 `ws_server.go` 中捕获 `emotion_update` 的值并持久化。

## 5. 统一标识符生成规范并重构问答聚合存储结构

### 问题分析
当前消息 ID 带有 `user-` 前缀，且问答数据被拆分为独立记录存储。如果系统未正常回复，会导致上下文错乱。必须将一问一答严格绑定为一个完整的存储单元。

### 修改方案
**前端修改**：
`frontend/src/renderer/services/wsManager.ts` 中，移除 `userMsgId` 的 `user-` 前缀，直接使用 `generateId()`。

**后端存储重构**：
1. **PG 模型 (`models.go`)**：
```go
// InteractionModel 对应 PostgreSQL 中的 interactions 表（问答聚合）
type InteractionModel struct {
	ID               string    `gorm:"column:id;primaryKey;type:varchar(64)"`
	SessionID        string    `gorm:"column:session_id;type:varchar(64);not null;index:idx_interactions_session_id_created_at"`
	MessageID        string    `gorm:"column:message_id;type:varchar(64);not null;unique"`
	UserContent      string    `gorm:"column:user_content;type:text;not null"`
	AssistantContent string    `gorm:"column:assistant_content;type:text;not null"`
	Thought          string    `gorm:"column:thought;type:text;not null;default:''"`
	Emotion          string    `gorm:"column:emotion;type:varchar(50);not null;default:''"`
	Error            string    `gorm:"column:error;type:text;not null;default:''"`
	CreatedAt        time.Time `gorm:"column:created_at;type:timestamp with time zone;default:CURRENT_TIMESTAMP;index:idx_interactions_session_id_created_at,sort:desc"`
}

func (InteractionModel) TableName() string {
	return "interactions"
}
```

2. **Redis 模型 (`chat_history_redis.go`)**：
```go
// Interaction 表示单次问答记录
type Interaction struct {
	MsgID            string `json:"msgId"`
	UserContent      string `json:"userContent"`
	AssistantContent string `json:"assistantContent"`
	Thought          string `json:"thought,omitempty"`
	Emotion          string `json:"emotion,omitempty"`
	Error            string `json:"error,omitempty"`
	Timestamp        int64  `json:"timestamp"`
}
```

3. **持久化逻辑 (`ws_server.go`)**：
在流式输出结束后，将用户输入和助手输出组装成一个完整的 `Interaction` 对象，一次性写入 PG 和 Redis。
```go
// 记录情绪
var fullAssistantEmotion string
// ... 在 switch msgType 中
case "emotion_update":
    fullAssistantEmotion = resp.Chunk

// ... 流结束后
go func() {
    bgCtx := context.Background()
    now := time.Now()

    // 错误处理：如果未正常生成回复
    errorJSON := ""
    if fullAssistantContent == "" {
        errorJSON = `{"error": "generation_failed", "details": "Assistant returned empty content"}`
        fullAssistantContent = errorJSON
    }

    interaction := repository.Interaction{
        MsgID:            cmdPayload.MsgID,
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
        MessageID:        cmdPayload.MsgID,
        UserContent:      cmdPayload.Message,
        AssistantContent: fullAssistantContent,
        Thought:          fullAssistantThought,
        Emotion:          fullAssistantEmotion,
        Error:            errorJSON,
        CreatedAt:        now,
    }

    // 异步写入 PG 和 Redis ...
}()
```

4. **历史记录组装 (`ws_server.go`)**：
从 Redis 读取 `Interaction` 列表后，将其展开为 `ChatMessage` 列表传给 Python。
```go
protoHistory := make([]*pb.ChatMessage, 0, len(recentHistory)*2)
for _, h := range recentHistory {
    protoHistory = append(protoHistory, &pb.ChatMessage{
        Role:    types.RoleUser,
        Content: h.UserContent,
    })
    if h.Error == "" {
        protoHistory = append(protoHistory, &pb.ChatMessage{
            Role:    types.RoleAssistant,
            Content: h.AssistantContent,
        })
    }
}
```
