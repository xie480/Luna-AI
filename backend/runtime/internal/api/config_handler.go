package api

import (
	"encoding/json"
	"net/http"

	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/logger"
	"go.uber.org/zap"
)

// ConfigHandler 处理配置相关的 HTTP 请求
type ConfigHandler struct {
	configManager *config.ConfigManager
	aiClient      *AIClient
}

// NewConfigHandler 创建 ConfigHandler
func NewConfigHandler(cm *config.ConfigManager, aiClient *AIClient) *ConfigHandler {
	return &ConfigHandler{
		configManager: cm,
		aiClient:      aiClient,
	}
}

// HandleUpdateConfig 处理更新配置请求（POST /api/v1/config）
// 由 Go 1.22+ 路由确保仅 POST 请求到达，不再冗余检查方法
func (h *ConfigHandler) HandleUpdateConfig(w http.ResponseWriter, r *http.Request) {
	var updates map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&updates); err != nil {
		writeJSON(w, http.StatusBadRequest, response{
			Code: 400,
			Msg:  "请求体格式错误",
		})
		return
	}

	ctx := r.Context()
	if err := h.configManager.UpdateConfig(ctx, updates); err != nil {
		logger.Error(ctx, "更新配置失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{
			Code: 500,
			Msg:  "更新配置失败",
		})
		return
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: map[string]bool{"success": true},
	})
}

// HandleGetConfig 处理获取配置请求（GET /api/v1/config）
// 由 Go 1.22+ 路由确保仅 GET 请求到达，不再冗余检查方法
func (h *ConfigHandler) HandleGetConfig(w http.ResponseWriter, r *http.Request) {
	cfg := h.configManager.GetConfig()

	safeConfig := map[string]interface{}{
		"has_llm_api_key": cfg.LLMAPIKey != "",
	}

	writeJSON(w, http.StatusOK, response{
		Code: 0,
		Msg:  "success",
		Data: safeConfig,
	})
}
