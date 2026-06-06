package repository

import (
	"context"
	"regexp"
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func setupTestPG(t *testing.T) (*gorm.DB, sqlmock.Sqlmock) {
	db, mock, err := sqlmock.New()
	require.NoError(t, err)

	dialector := postgres.New(postgres.Config{
		Conn:       db,
		DriverName: "postgres",
	})

	gormDB, err := gorm.Open(dialector, &gorm.Config{
		SkipDefaultTransaction: true,
	})
	require.NoError(t, err)

	return gormDB, mock
}

func TestChatHistoryPGRepo_SaveInteraction(t *testing.T) {
	db, mock := setupTestPG(t)
	repo := NewChatHistoryPGRepoWithDB(db)
	ctx := context.Background()

	now := time.Now()
	interaction := &InteractionModel{
		ID:               "123",
		SessionID:        "session-1",
		MessageID:        "msg-1",
		UserContent:      "hello",
		AssistantContent: "hi there",
		Thought:          "",
		Emotion:          "happy",
		Error:            "",
		CreatedAt:        now,
	}

	mock.ExpectQuery(regexp.QuoteMeta(`INSERT INTO "interactions" ("id","session_id","message_id","user_content","assistant_content","thought","emotion","error","created_at") VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING "created_at"`)).
		WithArgs(interaction.ID, interaction.SessionID, interaction.MessageID, interaction.UserContent, interaction.AssistantContent, interaction.Thought, interaction.Emotion, interaction.Error, interaction.CreatedAt).
		WillReturnRows(sqlmock.NewRows([]string{"created_at"}).AddRow(interaction.CreatedAt))

	err := repo.SaveInteraction(ctx, interaction)
	assert.NoError(t, err)
	assert.NoError(t, mock.ExpectationsWereMet())
}

func TestChatHistoryPGRepo_GetInteractionsBySessionID(t *testing.T) {
	db, mock := setupTestPG(t)
	repo := NewChatHistoryPGRepoWithDB(db)
	ctx := context.Background()

	now := time.Now()
	rows := sqlmock.NewRows([]string{"id", "session_id", "message_id", "user_content", "assistant_content", "thought", "emotion", "error", "created_at"}).
		AddRow("1", "session-1", "msg-1", "hello", "hi", "", "happy", "", now).
		AddRow("2", "session-1", "msg-2", "how are you", "I'm fine", "", "neutral", "", now)

	mock.ExpectQuery(regexp.QuoteMeta(`SELECT * FROM "interactions" WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2`)).
		WithArgs("session-1", 10).
		WillReturnRows(rows)

	interactions, err := repo.GetInteractionsBySessionID(ctx, "session-1", 10, 0)
	assert.NoError(t, err)
	assert.Len(t, interactions, 2)
	assert.Equal(t, "msg-1", interactions[0].MessageID)
	assert.Equal(t, "msg-2", interactions[1].MessageID)
	assert.Equal(t, "happy", interactions[0].Emotion)
	assert.NoError(t, mock.ExpectationsWereMet())
}
