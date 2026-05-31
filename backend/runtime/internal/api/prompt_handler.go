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

// HandleGetTemplates 处理获取所有模板列表请求（GET /api/v1/prompts/templates）
func (h *PromptHandler) HandleGetTemplates(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	templates, err := h.promptManager.ListTemplates(ctx)
	if err != nil {
		logger.Error(ctx, "获取模板列表失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "获取模板列表失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: templates,
	})
}

// HandleGetVersions 处理获取指定模板所有版本历史请求（GET /api/v1/prompts/templates/{id}/versions）
func (h *PromptHandler) HandleGetVersions(w http.ResponseWriter, r *http.Request) {
	// 从 URL 中提取模板 ID，路径格式: GET /api/v1/prompts/templates/{id}/versions
	templateID := r.PathValue("id")

	ctx := r.Context()
	versions, err := h.promptManager.GetVersions(ctx, templateID)
	if err != nil {
		logger.Error(ctx, "获取版本历史失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "获取版本历史失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: versions,
	})
}

// HandleCreateTemplate 处理创建模板请求（POST /api/v1/prompts/template）
func (h *PromptHandler) HandleCreateTemplate(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name         string `json:"name"`
		Category     string `json:"category"`
		SlotPosition string `json:"slot_position"`
		IsSystem     bool   `json:"is_system"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{
			Code: 400,
			Msg:  "请求体格式错误",
		})
		return
	}

	ctx := r.Context()
	tmpl, err := h.promptManager.CreateTemplate(ctx, req.Name, req.Category, req.SlotPosition, req.IsSystem)
	if err != nil {
		logger.Error(ctx, "创建模板失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "创建模板失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: tmpl,
	})
}

// HandleCreateVersion 处理创建版本请求（POST /api/v1/prompts/version）
func (h *PromptHandler) HandleCreateVersion(w http.ResponseWriter, r *http.Request) {
	var req struct {
		TemplateID string `json:"template_id"`
		Content    string `json:"content"`
		Variables  string `json:"variables"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{
			Code: 400,
			Msg:  "请求体格式错误",
		})
		return
	}

	ctx := r.Context()
	version, err := h.promptManager.CreateVersion(ctx, req.TemplateID, req.Content, req.Variables)
	if err != nil {
		logger.Error(ctx, "创建版本失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "创建版本失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: version,
	})
}

// HandlePublishVersion 处理发布版本请求（POST /api/v1/prompts/publish）
func (h *PromptHandler) HandlePublishVersion(w http.ResponseWriter, r *http.Request) {
	var req struct {
		TemplateID string `json:"template_id"`
		VersionID  string `json:"version_id"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{
			Code: 400,
			Msg:  "请求体格式错误",
		})
		return
	}

	ctx := r.Context()
	if err := h.promptManager.PublishVersion(ctx, req.TemplateID, req.VersionID); err != nil {
		logger.Error(ctx, "发布版本失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "发布版本失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: map[string]bool{"success": true},
	})
}

// HandleRollbackVersion 处理回滚版本请求（POST /api/v1/prompts/rollback）
func (h *PromptHandler) HandleRollbackVersion(w http.ResponseWriter, r *http.Request) {
	var req struct {
		TemplateID string `json:"template_id"`
		VersionID  string `json:"version_id"`
	}

	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{
			Code: 400,
			Msg:  "请求体格式错误",
		})
		return
	}

	ctx := r.Context()
	if err := h.promptManager.RollbackVersion(ctx, req.TemplateID, req.VersionID); err != nil {
		logger.Error(ctx, "回滚版本失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "回滚版本失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: map[string]bool{"success": true},
	})
}
