package repository

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"luna-ai/backend/runtime/internal/infrastructure"
)

func setupTestRedis(t *testing.T) (*infrastructure.RedisClient, *miniredis.Miniredis) {
	mr, err := miniredis.Run()
	require.NoError(t, err)

	client, err := infrastructure.NewRedisClient(mr.Addr(), "", 0)
	require.NoError(t, err)

	return client, mr
}

func TestChatHistoryRedisRepo_SaveMessage(t *testing.T) {
	client, mr := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewChatHistoryRedisRepo(client)
	ctx := context.Background()
	sessionID := "test-session-1"

	msg := ChatMessage{
		MsgID:     "msg-1",
		Role:      "user",
		Content:   "hello",
		Timestamp: time.Now().Unix(),
	}

	length, err := repo.SaveMessage(ctx, sessionID, msg)
	assert.NoError(t, err)
	assert.Equal(t, int64(1), length)

	// Verify in miniredis
	key := repo.buildHistoryKey(sessionID)
	list, err := client.GetClient().LRange(ctx, key, 0, -1).Result()
	assert.NoError(t, err)
	assert.Len(t, list, 1)
	assert.Contains(t, list[0], "msg-1")
}

func TestChatHistoryRedisRepo_GetContext(t *testing.T) {
	client, mr := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewChatHistoryRedisRepo(client)
	ctx := context.Background()
	sessionID := "test-session-2"

	// Setup data
	summaryKey := repo.buildSummaryKey(sessionID)
	mr.HSet(summaryKey, "core_summary", "test core summary")
	mr.HSet(summaryKey, "key_facts", "test key facts")

	msg1 := ChatMessage{MsgID: "msg-1", Role: "user", Content: "hello"}
	msg2 := ChatMessage{MsgID: "msg-2", Role: "assistant", Content: "hi"}
	_, _ = repo.SaveMessage(ctx, sessionID, msg1)
	_, _ = repo.SaveMessage(ctx, sessionID, msg2)

	// Test GetContext
	summary, history, err := repo.GetContext(ctx, sessionID)
	assert.NoError(t, err)

	assert.Equal(t, "test core summary", summary.CoreSummary)
	assert.Equal(t, "test key facts", summary.KeyFacts)
	assert.Len(t, history, 2)
	assert.Equal(t, "msg-1", history[0].MsgID)
	assert.Equal(t, "msg-2", history[1].MsgID)
}

func TestChatHistoryRedisRepo_UpdateSummaryAndTrim(t *testing.T) {
	client, mr := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewChatHistoryRedisRepo(client)
	ctx := context.Background()
	sessionID := "test-session-3"

	// Setup data
	for i := 0; i < 5; i++ {
		msg := ChatMessage{MsgID: fmt.Sprintf("msg-%d", i), Content: "test"}
		_, _ = repo.SaveMessage(ctx, sessionID, msg)
	}

	newSummary := ChatSummary{
		CoreSummary: "new core summary",
		KeyFacts:    "new key facts",
	}

	// Trim first 2 messages (keep from index 2)
	err := repo.UpdateSummaryAndTrim(ctx, sessionID, newSummary, 2)
	assert.NoError(t, err)

	// Verify
	summary, history, err := repo.GetContext(ctx, sessionID)
	assert.NoError(t, err)

	assert.Equal(t, "new core summary", summary.CoreSummary)
	assert.Equal(t, "new key facts", summary.KeyFacts)
	assert.Len(t, history, 3)
	assert.Equal(t, "msg-2", history[0].MsgID)
	assert.Equal(t, "msg-4", history[2].MsgID)
}
