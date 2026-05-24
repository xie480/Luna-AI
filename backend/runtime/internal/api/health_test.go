package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"luna-ai/backend/runtime/internal/types"
)

func TestHealthCheckHandler(t *testing.T) {
	req, err := http.NewRequest("GET", "/health", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("X-Trace-ID", "test-trace-123")

	rr := httptest.NewRecorder()
	handler := http.HandlerFunc(HealthCheckHandler)

	handler.ServeHTTP(rr, req)

	if status := rr.Code; status != http.StatusOK {
		t.Errorf("handler returned wrong status code: got %v want %v",
			status, http.StatusOK)
	}

	var resp types.Response
	if err := json.NewDecoder(rr.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}

	if resp.Code != types.CodeSuccess {
		t.Errorf("expected success code, got %v", resp.Code)
	}

	if resp.TraceID != "test-trace-123" {
		t.Errorf("expected trace_id test-trace-123, got %v", resp.TraceID)
	}
}
