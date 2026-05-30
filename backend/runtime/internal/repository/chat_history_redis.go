package repository

import (
	"context"
	"encoding/json"
	"fmt"

	"luna-ai/backend/runtime/internal/infrastructure"

	"github.com/redis/go-redis/v9"
)

const (
	MemWorkingWindowSize = 50 // 触发压缩的阈值（以 Interaction 为单位）
	MemCompressBatchSize = 20 // 每次压缩的 Interaction 数量
)

// Interaction 表示单次问答记录（Redis 缓存层）
// 将用户的一问与系统的一答严格绑定为一个完整的存储单元。
// 如果在交互中系统未正常生成回复，Error 字段非空，AssistantContent 存储标准报错 JSON。
type Interaction struct {
	MsgID            string `json:"msgId"`
	UserContent      string `json:"userContent"`
	AssistantContent string `json:"assistantContent"`
	// Thought 字段存储助手消息的内心独白（thought），用于记忆系统展示历史心理状态
	Thought string `json:"thought,omitempty"`
	// Emotion 字段存储助手回复时的情绪状态，确保宕机或重启后能恢复情绪上下文
	Emotion   string `json:"emotion,omitempty"`
	Error     string `json:"error,omitempty"`
	Timestamp int64  `json:"timestamp"`
}

// ChatSummary 表示聊天摘要
// 仅包含 core_summary 和 key_facts 两个核心字段，移除冗余的 short_term_memory
type ChatSummary struct {
	CoreSummary string `json:"core_summary"`
	KeyFacts    string `json:"key_facts"`
}

// ChatHistoryRedisRepo 封装 Redis 短期记忆与摘要读写
type ChatHistoryRedisRepo struct {
	redis *infrastructure.RedisClient
}

// NewChatHistoryRedisRepo 创建 ChatHistoryRedisRepo 实例
func NewChatHistoryRedisRepo(r *infrastructure.RedisClient) *ChatHistoryRedisRepo {
	return &ChatHistoryRedisRepo{redis: r}
}

func (r *ChatHistoryRedisRepo) buildHistoryKey(sessionID string) string {
	return fmt.Sprintf("luna:mem:chat:%s:history", sessionID)
}

func (r *ChatHistoryRedisRepo) buildSummaryKey(sessionID string) string {
	return fmt.Sprintf("luna:mem:chat:%s:summary", sessionID)
}

// SaveInteraction 追加问答交互记录（一问一答绑定为完整单元）并返回当前长度
func (r *ChatHistoryRedisRepo) SaveInteraction(ctx context.Context, sessionID string, interaction Interaction) (int64, error) {
	key := r.buildHistoryKey(sessionID)
	data, err := json.Marshal(interaction)
	if err != nil {
		return 0, fmt.Errorf("序列化 Interaction 失败: %w", err)
	}

	// RPush 并返回长度
	length, err := r.redis.GetClient().RPush(ctx, key, data).Result()
	if err != nil {
		return 0, fmt.Errorf("写入 Redis 失败: %w", err)
	}
	return length, nil
}

// GetContext 获取当前上下文 (摘要 + 历史 Interaction 列表)
func (r *ChatHistoryRedisRepo) GetContext(ctx context.Context, sessionID string) (ChatSummary, []Interaction, error) {
	historyKey := r.buildHistoryKey(sessionID)
	summaryKey := r.buildSummaryKey(sessionID)

	// 使用 Pipeline 同时获取摘要和历史
	pipe := r.redis.GetClient().Pipeline()
	summaryCmd := pipe.HGetAll(ctx, summaryKey)
	historyCmd := pipe.LRange(ctx, historyKey, 0, -1)
	_, err := pipe.Exec(ctx)

	if err != nil && err != redis.Nil {
		return ChatSummary{}, nil, fmt.Errorf("从 Redis 获取上下文失败: %w", err)
	}

	summaryMap := summaryCmd.Val()
	summary := ChatSummary{
		CoreSummary: summaryMap["core_summary"],
		KeyFacts:    summaryMap["key_facts"],
	}

	strs := historyCmd.Val()
	var history []Interaction
	for _, s := range strs {
		var interaction Interaction
		if err := json.Unmarshal([]byte(s), &interaction); err == nil {
			history = append(history, interaction)
		}
	}
	return summary, history, nil
}

// UpdateSummaryAndTrim 更新摘要并移除已压缩的旧 Interaction 记录
// 做什么：使用 Redis Pipeline 原子化地更新摘要字段并裁剪历史记录
// 为什么这样做：确保摘要更新和历史裁剪在同一事务中完成，防止数据不一致
// 输入输出：
//   - 输入：sessionID, summary (仅包含 core_summary 和 key_facts), trimCount (要删除的记录数)
//   - 输出：error (操作失败时返回错误)
//
// 边界条件：trimCount 必须大于 0，否则不执行裁剪
// 异常行为：Pipeline 执行失败时返回错误，不进行部分更新
func (r *ChatHistoryRedisRepo) UpdateSummaryAndTrim(ctx context.Context, sessionID string, summary ChatSummary, trimCount int64) error {
	historyKey := r.buildHistoryKey(sessionID)
	summaryKey := r.buildSummaryKey(sessionID)

	pipe := r.redis.GetClient().Pipeline()

	// 1. 仅更新 core_summary 和 key_facts 两个核心字段
	pipe.HSet(ctx, summaryKey, "core_summary", summary.CoreSummary, "key_facts", summary.KeyFacts)

	// 2. 裁剪历史记录：保留从 trimCount 开始到末尾的元素
	// LTrim 范围是 start 到 stop，例如 trimCount=20，则保留索引 20 到 -1 的元素
	// 即删除了最旧的 20 条记录（索引 0-19）
	pipe.LTrim(ctx, historyKey, trimCount, -1)

	_, err := pipe.Exec(ctx)
	if err != nil {
		return fmt.Errorf("更新摘要并裁剪历史失败: %w", err)
	}
	return nil
}
