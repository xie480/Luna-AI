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

func TestChatHistoryPGRepo_SaveMessage(t *testing.T) {
	db, mock := setupTestPG(t)
	repo := NewChatHistoryPGRepoWithDB(db)
	ctx := context.Background()

	now := time.Now()
	msg := &ChatMessageModel{
		ID:        "123",
		SessionID: "session-1",
		MsgID:     "msg-1",
		Role:      "user",
		Content:   "hello",
		CreatedAt: now,
	}

	mock.ExpectQuery(regexp.QuoteMeta(`INSERT INTO "chat_messages" ("id","session_id","msg_id","role","content","created_at") VALUES ($1,$2,$3,$4,$5,$6) RETURNING "created_at"`)).
		WithArgs(msg.ID, msg.SessionID, msg.MsgID, msg.Role, msg.Content, msg.CreatedAt).
		WillReturnRows(sqlmock.NewRows([]string{"created_at"}).AddRow(msg.CreatedAt))

	err := repo.SaveMessage(ctx, msg)
	assert.NoError(t, err)
	assert.NoError(t, mock.ExpectationsWereMet())
}

func TestChatHistoryPGRepo_GetMessagesBySessionID(t *testing.T) {
	db, mock := setupTestPG(t)
	repo := NewChatHistoryPGRepoWithDB(db)
	ctx := context.Background()

	now := time.Now()
	rows := sqlmock.NewRows([]string{"id", "session_id", "msg_id", "role", "content", "created_at"}).
		AddRow("1", "session-1", "msg-1", "user", "hello", now).
		AddRow("2", "session-1", "msg-2", "assistant", "hi", now)

	mock.ExpectQuery(regexp.QuoteMeta(`SELECT * FROM "chat_messages" WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2`)).
		WithArgs("session-1", 10).
		WillReturnRows(rows)

	messages, err := repo.GetMessagesBySessionID(ctx, "session-1", 10, 0)
	assert.NoError(t, err)
	assert.Len(t, messages, 2)
	assert.Equal(t, "msg-1", messages[0].MsgID)
	assert.Equal(t, "msg-2", messages[1].MsgID)
	assert.NoError(t, mock.ExpectationsWereMet())
}
