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

// HandleUpdateConfig 处理更新配置请求
func (h *ConfigHandler) HandleUpdateConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var updates map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&updates); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	if err := h.configManager.UpdateConfig(ctx, updates); err != nil {
		logger.Error(ctx, "更新配置失败", zap.Error(err))
		http.Error(w, "Failed to update config", http.StatusInternalServerError)
		return
	}

	// 响应成功
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]bool{"success": true})
}

// HandleGetConfig 处理获取配置请求
func (h *ConfigHandler) HandleGetConfig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	cfg := h.configManager.GetConfig()
	
	// 注意：不要返回明文的敏感信息，这里只返回掩码后的信息或非敏感信息
	safeConfig := map[string]interface{}{
		"has_llm_api_key": cfg.LLMAPIKey != "",
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(safeConfig)
}
