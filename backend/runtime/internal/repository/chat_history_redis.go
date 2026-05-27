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

// ChatMessage 表示单条聊天记录
type ChatMessage struct {
	MsgID     string `json:"msgId"`
	Role      string `json:"role"`
	Content   string `json:"content"`
	// Thought 字段存储助手消息的内心独白（thought），用于记忆系统展示历史心理状态
	// 仅 assistant 角色有此字段，user/system 角色为空字符串
	Thought   string `json:"thought,omitempty"`
	Timestamp int64  `json:"timestamp"`
}

// ChatSummary 表示聊天摘要
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

// SaveMessage 追加消息并返回当前长度，以便调用方决定是否触发压缩
func (r *ChatHistoryRedisRepo) SaveMessage(ctx context.Context, sessionID string, msg ChatMessage) (int64, error) {
	key := r.buildHistoryKey(sessionID)
	data, err := json.Marshal(msg)
	if err != nil {
		return 0, fmt.Errorf("序列化消息失败: %w", err)
	}

	// RPush 并返回长度
	length, err := r.redis.GetClient().RPush(ctx, key, data).Result()
	if err != nil {
		return 0, fmt.Errorf("写入 Redis 失败: %w", err)
	}
	return length, nil
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
		return ChatSummary{}, nil, fmt.Errorf("从 Redis 获取上下文失败: %w", err)
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
	if err != nil {
		return fmt.Errorf("更新摘要并裁剪历史失败: %w", err)
	}
	return nil
}
