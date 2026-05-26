# 对话历史记录存储迁移技术实现计划 (滑动窗口 + 摘要压缩方案)

## 1. 背景与目标
当前 Luna 系统的对话历史记录（History）依赖前端在每次请求时全量传递，这不仅增加了网络传输开销，也存在状态不一致和前端被篡改的风险。为实现后端（Go Runtime）对状态的绝对控制（SSOT），并遵循《多层记忆系统设计》中关于“工作记忆”与“事实记忆”分离的原则，计划将对话历史记录的存储迁移至后端的 **Redis + PostgreSQL 双写架构**，并引入**两段式摘要压缩策略**以解决长对话上下文丢失的问题。

## 2. 存储设计方案 (冷热分离 + 摘要压缩)

本方案的核心思想是：**让 Redis 负责高速缓存与短期上下文维持（热数据），让 PostgreSQL 负责海量对话数据的永久归档（冷数据）。同时，当 Redis 中的对话轮数达到阈值时，触发后台摘要压缩，将旧对话提炼为核心摘要（Summary）保留在上下文中，从而在不丢失关键信息的前提下控制 Token 消耗。**

### 2.1 Redis 设计 (短期工作记忆)
- **数据结构**: 
  - 近期原始对话: Redis `List`
  - 会话摘要: Redis `Hash` (包含 `core_summary` 和 `key_facts` 两个独立字段)
- **键名格式**: 
  - 原始对话: `luna:mem:chat:{session_id}:history`
  - 会话摘要: `luna:mem:chat:{session_id}:summary`
- **数据载荷 (Payload)**: 
  - `history` 列表中的每个元素为 JSON 序列化后的单条消息对象。
  - `summary` Hash 包含两个字段：
    - `core_summary`: 字符串，记录对话的核心梗概。
    - `key_facts`: 字符串（或 JSON 序列化的数组），记录提取出的关键事实。
- **生命周期管理**: 采用**滑动窗口**机制。当 `history` 列表长度超过阈值（如 `MEM_WORKING_WINDOW_SIZE` = 20）时，触发摘要压缩流程。

### 2.2 PostgreSQL 设计 (长期全量归档)
- **表名**: `chat_messages`
- **表结构设计**:
  ```sql
  CREATE TABLE chat_messages (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      session_id VARCHAR(64) NOT NULL,
      msg_id VARCHAR(64) NOT NULL UNIQUE,
      role VARCHAR(20) NOT NULL, -- 'user', 'assistant', 'system'
      content TEXT NOT NULL,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX idx_chat_messages_session_id_created_at ON chat_messages(session_id, created_at DESC);
  ```

## 3. 数据读写与摘要压缩逻辑

### 3.1 写入逻辑 (双写)
1. **收到用户消息/AI回复完成时**:
   - **写 PG**: 异步（或同步）将消息插入 PostgreSQL 的 `chat_messages` 表，实现全量永久归档。
   - **写 Redis**: 将消息 `RPUSH` 到 Redis 的 `history` List 中。

### 3.2 摘要压缩逻辑 (后台触发)
1. **阈值检测**: 每次写入 Redis 后，检查 `history` 列表的长度。如果长度超过 `MEM_WORKING_WINDOW_SIZE`（例如 20 轮）。
2. **触发压缩**: Go Runtime 异步调用 Python AI 服务的 `SummarizeContext` 接口。
   - **输入**: 当前 Redis 中的 `summary` Hash (如果有) + `history` 中最早的 N 条消息（例如前 10 条）。
   - **输出**: 新的 `core_summary` (核心概括) 和 `key_facts` (关键事实，用于后续转存长期记忆)。
3. **状态更新**:
   - 使用 `HSET` 将新的 `core_summary` 和 `key_facts` 覆盖写入 Redis 的 `summary` Hash 键。
   - 使用 `LPOP` 或 `LTRIM` 从 Redis 的 `history` 列表中移除已被压缩的那 N 条旧消息。

### 3.3 读取逻辑 (组装上下文)
- **AI 上下文读取 (高频)**:
  - 当需要组装 Prompt 发给大模型时，Go Runtime 从 Redis 读取：
    1. `HGETALL luna:mem:chat:{session_id}:summary` (获取 `core_summary` 和 `key_facts`)。
    2. `LRANGE luna:mem:chat:{session_id}:history 0 -1` (获取近期的精确对话上下文)。
  - **模板注入**: 将获取到的 `core_summary` 和 `key_facts` 分别注入到 `memory.j2` 模板的 `{{CORE_SUMMARY}}` 和 `{{KEY_FACTS}}` 占位符中。将 `history` 转换为对话格式注入到 `runtime.j2` 或作为消息列表传递。
  - **优势**: 既保留了长期的核心背景（通过摘要），又提供了近期的精确细节（通过滑动窗口），完美平衡了上下文完整性与 Token 消耗。
- **前端历史记录翻页 (低频)**:
  - 当用户在 UI 上向上滚动，想要查看更早的历史聊天时，前端调用新的 HTTP/WS 接口，后端直接从 PostgreSQL 中按 `session_id` 分页查询。

## 4. 方案优劣势评估

| 特性 | 纯 Redis 方案 (无 TTL) | 简单 LTRIM 方案 | 滑动窗口 + 摘要压缩方案 (本方案) |
| :--- | :--- | :--- | :--- |
| **内存占用** | 极高。 | 极低且恒定。 | **极低且恒定**。 |
| **硬盘占用** | 较低。 | 正常。 | **正常** (全量归档在 PG)。 |
| **上下文控制** | 易 Token 溢出。 | 天然截断。 | **智能截断**。结合摘要，Token 消耗稳定。 |
| **历史检索** | 极差。 | 极佳 (依赖 PG)。 | **极佳** (依赖 PG)。 |
| **上下文完整性** | 完整但冗余。 | **丢失旧信息** (体验差)。 | **核心信息不丢失** (通过摘要保留背景)。 |
| **系统契合度** | 违背架构。 | 部分契合。 | **完美契合**《多层记忆系统设计》的两段式压缩策略。 |

## 5. 重构思路与业务逻辑改造

### 5.1 目录结构调整
在 `backend/runtime/internal/` 下新增 `repository` 层，用于隔离数据访问逻辑：
```text
backend/runtime/internal/
├── repository/
│   ├── chat_history_redis.go    # 封装 Redis 短期记忆与摘要读写
│   └── chat_history_pg.go       # 封装 PostgreSQL 长期归档读写
```

### 5.2 业务逻辑改造 (ws_server.go)
1. **前端减负**: 前端 `CMD_USER_INPUT` 载荷中不再需要传递完整的 `History` 数组，仅需传递 `SessionID` 和当前 `Message`。
2. **接收请求**: Go 收到请求后，构造 User 消息对象，调用 Repository 执行双写。
3. **组装上下文**: Go 调用 Redis Repository 获取 `Summary` (包含 `core_summary` 和 `key_facts`) 和 `RecentHistory`，组装成 `pb.ChatRequest` 发送给 Python AI 服务。
4. **流式响应处理**: Go 接收 AI 的流式响应并转发给前端。在流结束（`IsFinished == true`）时，将完整的 AI 回复内容构造为 Assistant 消息对象，调用 Repository 执行双写。
5. **触发压缩**: 在双写完成后，检查 Redis List 长度，若超限则异步触发摘要压缩流程。

## 6. 持久层接口改造说明

### 6.1 定义 Repository 接口
在 `backend/runtime/internal/repository/chat_history_redis.go` 中定义：

```go
package repository

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/redis/go-redis/v9"
	"luna-ai/backend/runtime/internal/infrastructure"
)

const (
	MemWorkingWindowSize = 20 // 触发压缩的阈值
	MemCompressBatchSize = 10 // 每次压缩的消息数量
)

type ChatMessage struct {
	MsgID     string `json:"msgId"`
	Role      string `json:"role"`
	Content   string `json:"content"`
	Timestamp int64  `json:"timestamp"`
}

type ChatSummary struct {
	CoreSummary string `json:"core_summary"`
	KeyFacts    string `json:"key_facts"`
}

type ChatHistoryRedisRepo struct {
	redis *infrastructure.RedisClient
}

func NewChatHistoryRedisRepo(r *infrastructure.RedisClient) *ChatHistoryRedisRepo {
	return &ChatHistoryRedisRepo{redis: r}
}

func (r *ChatHistoryRedisRepo) buildHistoryKey(sessionID string) string {
	return fmt.Sprintf("luna:mem:chat:%s:history", sessionID)
}

func (r *ChatHistoryRedisRepo) buildSummaryKey(sessionID string) string {
	return fmt.Sprintf("luna:mem:chat:%s:summary", sessionID)
}

// SaveMessage 追加消息并返回当前长度，以便调用方决定是否触发压缩
func (r *ChatHistoryRedisRepo) SaveMessage(ctx context.Context, sessionID string, msg ChatMessage) (int64, error) {
	key := r.buildHistoryKey(sessionID)
	data, err := json.Marshal(msg)
	if err != nil {
		return 0, err
	}
	
	// RPush 并返回长度
	length, err := r.redis.GetClient().RPush(ctx, key, data).Result()
	return length, err
}

// GetContext 获取当前上下文 (摘要 + 近期历史)
func (r *ChatHistoryRedisRepo) GetContext(ctx context.Context, sessionID string) (ChatSummary, []ChatMessage, error) {
	historyKey := r.buildHistoryKey(sessionID)
	summaryKey := r.buildSummaryKey(sessionID)

	// 使用 Pipeline 同时获取摘要和历史
	pipe := r.redis.GetClient().Pipeline()
	summaryCmd := pipe.HGetAll(ctx, summaryKey)
	historyCmd := pipe.LRange(ctx, historyKey, 0, -1)
	_, err := pipe.Exec(ctx)
	
	if err != nil && err != redis.Nil {
		return ChatSummary{}, nil, err
	}

	summaryMap := summaryCmd.Val()
	summary := ChatSummary{
		CoreSummary: summaryMap["core_summary"],
		KeyFacts:    summaryMap["key_facts"],
	}

	strs := historyCmd.Val()
	var history []ChatMessage
	for _, s := range strs {
		var msg ChatMessage
		if err := json.Unmarshal([]byte(s), &msg); err == nil {
			history = append(history, msg)
		}
	}
	return summary, history, nil
}

// UpdateSummaryAndTrim 更新摘要并移除已压缩的旧消息
func (r *ChatHistoryRedisRepo) UpdateSummaryAndTrim(ctx context.Context, sessionID string, summary ChatSummary, trimCount int64) error {
	historyKey := r.buildHistoryKey(sessionID)
	summaryKey := r.buildSummaryKey(sessionID)

	pipe := r.redis.GetClient().Pipeline()
	pipe.HSet(ctx, summaryKey, "core_summary", summary.CoreSummary, "key_facts", summary.KeyFacts)
	// 保留从 trimCount 开始到末尾的元素
	pipe.LTrim(ctx, historyKey, trimCount, -1)
	_, err := pipe.Exec(ctx)
	return err
}
```

## 7. 分步开发与测试路线图

### Phase 1: 基础设施与 Repository 层实现
- [ ] 在 PostgreSQL 中创建 `chat_messages` 表。
- [ ] 创建 `repository/chat_history_redis.go`，实现 Redis 的读写、摘要更新（Hash 结构）和裁剪逻辑。
- [ ] 创建 `repository/chat_history_pg.go`，实现 PostgreSQL 的插入和分页查询逻辑。
- [ ] 编写单元测试，验证 Redis 的 Pipeline 操作和 PG 的插入逻辑。

### Phase 2: 核心业务逻辑改造 (Go Runtime)
- [ ] 修改 `ws_server.go` 中的 `CMDUserInputPayload`，标记 `History` 字段为废弃或可选。
- [ ] 在 `handleChatRequest` 中接入 Repository：
  - 收到请求时，执行双写保存 User 消息。
  - 从 Redis 拉取 `Summary` (包含 `core_summary` 和 `key_facts`) 和 `RecentHistory`，组装 `pb.ChatRequest`。
- [ ] 在流式响应结束处（`resp.IsFinished == true`），收集完整的 Chunk，执行双写保存 Assistant 消息。
- [ ] **新增逻辑**: 在双写完成后，检查 Redis List 长度，若超过 `MemWorkingWindowSize`，则启动 Goroutine 调用 Python 的 `SummarizeContext` 接口，并在成功后调用 `UpdateSummaryAndTrim`。

### Phase 3: Python AI 服务适配
- [ ] 确保 Python 端的 `SummarizeContext` 接口能够正确返回 `core_summary` 和 `key_facts`。
- [ ] 确保 Python 端在处理 `ChatRequest` 时，能够正确解析并注入 `core_summary` 和 `key_facts` 到 `memory.j2` 模板中。

### Phase 4: 前端适配与联调
- [ ] 修改前端 `sessionStore.ts`，发送消息时不再携带全量 `history`。
- [ ] 启动前后端进行端到端联调，验证多轮对话后，摘要是否成功生成，且 AI 是否能基于摘要回答早期的问题。

### Phase 5: 历史记录翻页功能 (可选/后续迭代)
- [ ] 在 Go Runtime 中新增一个处理历史记录分页查询的 WS/HTTP 接口。
- [ ] 前端实现向上滚动加载更多历史记录的 UI 交互。