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

func TestChatHistoryRedisRepo_SaveInteraction(t *testing.T) {
	client, mr := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewChatHistoryRedisRepo(client)
	ctx := context.Background()
	sessionID := "test-session-1"

	interaction := Interaction{
		MsgID:            "interaction-1",
		UserContent:      "hello",
		AssistantContent: "hi there!",
		Thought:          "I am thinking...",
		Emotion:          "Happy",
		Timestamp:        time.Now().Unix(),
	}

	length, err := repo.SaveInteraction(ctx, sessionID, interaction)
	assert.NoError(t, err)
	assert.Equal(t, int64(1), length)

	// Verify in miniredis
	key := repo.buildHistoryKey(sessionID)
	list, err := client.GetClient().LRange(ctx, key, 0, -1).Result()
	assert.NoError(t, err)
	assert.Len(t, list, 1)
	assert.Contains(t, list[0], "interaction-1")
	assert.Contains(t, list[0], "hi there!")
	assert.Contains(t, list[0], "Happy")
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

	interaction1 := Interaction{MsgID: "interaction-1", UserContent: "hello", AssistantContent: "hi there!"}
	interaction2 := Interaction{MsgID: "interaction-2", UserContent: "how are you?", AssistantContent: "I am fine!", Emotion: "Happy"}
	_, _ = repo.SaveInteraction(ctx, sessionID, interaction1)
	_, _ = repo.SaveInteraction(ctx, sessionID, interaction2)

	// Test GetContext
	summary, history, err := repo.GetContext(ctx, sessionID)
	assert.NoError(t, err)

	assert.Equal(t, "test core summary", summary.CoreSummary)
	assert.Equal(t, "test key facts", summary.KeyFacts)
	assert.Len(t, history, 2)
	assert.Equal(t, "interaction-1", history[0].MsgID)
	assert.Equal(t, "interaction-2", history[1].MsgID)
	assert.Equal(t, "Happy", history[1].Emotion)
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
		interaction := Interaction{
			MsgID:            fmt.Sprintf("interaction-%d", i),
			UserContent:      fmt.Sprintf("user msg %d", i),
			AssistantContent: fmt.Sprintf("assistant reply %d", i),
		}
		_, _ = repo.SaveInteraction(ctx, sessionID, interaction)
	}

	newSummary := ChatSummary{
		CoreSummary: "new core summary",
		KeyFacts:    "new key facts",
	}

	// Trim first 2 interactions (keep from index 2)
	err := repo.UpdateSummaryAndTrim(ctx, sessionID, newSummary, 2)
	assert.NoError(t, err)

	// Verify
	summary, history, err := repo.GetContext(ctx, sessionID)
	assert.NoError(t, err)

	assert.Equal(t, "new core summary", summary.CoreSummary)
	assert.Equal(t, "new key facts", summary.KeyFacts)
	assert.Len(t, history, 3)
	assert.Equal(t, "interaction-2", history[0].MsgID)
	assert.Equal(t, "interaction-4", history[2].MsgID)
}
