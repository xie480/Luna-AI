package api

import (
	"encoding/json"
	"net/http"

	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/prompt"
	"go.uber.org/zap"
)

// PromptHandler 处理 Prompt 相关的 HTTP 请求
type PromptHandler struct {
	promptManager *prompt.Manager
}

// NewPromptHandler 创建 PromptHandler
func NewPromptHandler(pm *prompt.Manager) *PromptHandler {
	return &PromptHandler{
		promptManager: pm,
	}
}

// HandleCreateTemplate 处理创建模板请求
func (h *PromptHandler) HandleCreateTemplate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		Name         string `json:"name"`
		Category     string `json:"category"`
		SlotPosition string `json:"slot_position"`
		IsSystem     bool   `json:"is_system"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	tmpl, err := h.promptManager.CreateTemplate(ctx, req.Name, req.Category, req.SlotPosition, req.IsSystem)
	if err != nil {
		logger.Error(ctx, "创建模板失败", zap.Error(err))
		http.Error(w, "Failed to create template", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tmpl)
}

// HandleCreateVersion 处理创建版本请求
func (h *PromptHandler) HandleCreateVersion(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		TemplateID string `json:"template_id"`
		Content    string `json:"content"`
		Variables  string `json:"variables"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	version, err := h.promptManager.CreateVersion(ctx, req.TemplateID, req.Content, req.Variables)
	if err != nil {
		logger.Error(ctx, "创建版本失败", zap.Error(err))
		http.Error(w, "Failed to create version", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(version)
}

// HandlePublishVersion 处理发布版本请求
func (h *PromptHandler) HandlePublishVersion(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req struct {
		TemplateID string `json:"template_id"`
		VersionID  string `json:"version_id"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	if err := h.promptManager.PublishVersion(ctx, req.TemplateID, req.VersionID); err != nil {
		logger.Error(ctx, "发布版本失败", zap.Error(err))
		http.Error(w, "Failed to publish version", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]bool{"success": true})
}
