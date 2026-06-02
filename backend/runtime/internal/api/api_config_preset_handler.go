package api

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"go.uber.org/zap"
	"luna-ai/backend/runtime/internal/config"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
	pb "luna-ai/backend/runtime/shared/proto"
)

// ApiConfigPresetHandler 处理 API 配置预设相关的 HTTP 请求
type ApiConfigPresetHandler struct {
    repo      *repository.ConfigPresetPGRepo
    cryptoSvc *config.CryptoService
    aiClient  *AIClient
    configMgr *config.Manager
}

// NewApiConfigPresetHandler 创建 ApiConfigPresetHandler
func NewApiConfigPresetHandler(repo *repository.ConfigPresetPGRepo, cryptoSvc *config.CryptoService, aiClient *AIClient, cfgMgr *config.Manager) *ApiConfigPresetHandler {
    return &ApiConfigPresetHandler{
        repo:      repo,
        cryptoSvc: cryptoSvc,
        aiClient:  aiClient,
        configMgr: cfgMgr,
    }
}

// ModelConfig 定义模型配置的 JSON 结构
type ModelConfig struct {
	BaseURL     string  `json:"base_url"`
	APIKey      string  `json:"api_key"`
	ModelID          string  `json:"model_id"`
	MaxTokens        int32   `json:"max_tokens"`
	MaxContextTokens int32   `json:"max_context_tokens"`
	Temperature      float32 `json:"temperature"`
}

// PresetRequest 定义创建/更新预设的请求体
type PresetRequest struct {
	ID                string      `json:"id"`
	Name              string      `json:"name"`
	LargeModelConfig  ModelConfig `json:"large_model_config"`
	MediumModelConfig ModelConfig `json:"medium_model_config"`
	SmallModelConfig  ModelConfig `json:"small_model_config"`
}

// PresetResponse 定义返回给前端的预设结构（API Key 脱敏）
type PresetResponse struct {
	ID                string      `json:"id"`
	Name              string      `json:"name"`
	IsActive          bool        `json:"is_active"`
	LargeModelConfig  ModelConfig `json:"large_model_config"`
	MediumModelConfig ModelConfig `json:"medium_model_config"`
	SmallModelConfig  ModelConfig `json:"small_model_config"`
}

// HandleGetPresets 获取所有预设列表
func (h *ApiConfigPresetHandler) HandleGetPresets(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	presets, err := h.repo.GetAll(ctx)
	if err != nil {
		logger.Error(ctx, "获取预设列表失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "获取预设列表失败"})
		return
	}

	var respData []PresetResponse
	for _, p := range presets {
		respData = append(respData, h.toPresetResponse(p))
	}

	writeJSON(w, http.StatusOK, response{Code: 0, Msg: "success", Data: respData})
}

// HandleSavePreset 创建或更新预设
func (h *ApiConfigPresetHandler) HandleSavePreset(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	var req PresetRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "请求体格式错误"})
		return
	}

	if req.Name == "" {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "预设名称不能为空"})
		return
	}

	// 加密 API Key
	largeConfig, err := h.encryptModelConfig(req.LargeModelConfig)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "加密大模型配置失败"})
		return
	}
	mediumConfig, err := h.encryptModelConfig(req.MediumModelConfig)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "加密中模型配置失败"})
		return
	}
	smallConfig, err := h.encryptModelConfig(req.SmallModelConfig)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "加密小模型配置失败"})
		return
	}

	preset := &repository.ApiConfigPreset{
		ID:                req.ID,
		Name:              req.Name,
		LargeModelConfig:  largeConfig,
		MediumModelConfig: mediumConfig,
		SmallModelConfig:  smallConfig,
	}

	if preset.ID == "" {
		preset.ID = snowflake.GenerateStringID()
	}

	if err := h.repo.Save(ctx, preset); err != nil {
		logger.Error(ctx, "保存预设失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "保存预设失败"})
		return
	}

	writeJSON(w, http.StatusOK, response{Code: 0, Msg: "success", Data: map[string]string{"id": preset.ID}})
}

// HandleActivatePreset 激活预设并同步到 Python
func (h *ApiConfigPresetHandler) HandleActivatePreset(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()
    id := r.PathValue("id")
    if id == "" {
        writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "缺少预设 ID"})
        return
    }

    // 使用 ConfigManager 进行激活并同步（内部包含 DB 更新、内存快照和事件发布）
    if err := h.configMgr.ActivatePreset(ctx, id); err != nil {
        logger.Error(ctx, "激活预设失败", zap.Error(err))
        writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "激活预设失败"})
        return
    }

    writeJSON(w, http.StatusOK, response{Code: 0, Msg: "success"})
}

// FetchModelsRequest 定义获取模型列表的请求体
type FetchModelsRequest struct {
	BaseURL string `json:"base_url"`
	APIKey  string `json:"api_key"`
}

// FetchModelsResponse 定义获取模型列表的响应体
type FetchModelsResponse struct {
	Data []struct {
		ID string `json:"id"`
	} `json:"data"`
}

// HandleFetchModels 代理请求目标 API 获取可用模型列表
func (h *ApiConfigPresetHandler) HandleFetchModels(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	var req FetchModelsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "请求体格式错误"})
		return
	}

	if req.BaseURL == "" {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "Base URL 不能为空"})
		return
	}

	// 构造目标 URL
	targetURL := strings.TrimSuffix(req.BaseURL, "/") + "/models"

	// 创建 HTTP 请求
	httpReq, err := http.NewRequestWithContext(ctx, "GET", targetURL, nil)
	if err != nil {
		logger.Error(ctx, "创建请求失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "创建请求失败"})
		return
	}

	if req.APIKey != "" {
		httpReq.Header.Set("Authorization", "Bearer "+req.APIKey)
	}

	// 发送请求
	client := &http.Client{}
	resp, err := client.Do(httpReq)
	if err != nil {
		logger.Error(ctx, "请求目标 API 失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "请求目标 API 失败"})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		logger.Error(ctx, "目标 API 返回错误", zap.Int("status", resp.StatusCode), zap.String("body", string(bodyBytes)))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "目标 API 返回错误"})
		return
	}

	// 解析响应
	var fetchResp FetchModelsResponse
	if err := json.NewDecoder(resp.Body).Decode(&fetchResp); err != nil {
		// 尝试直接读取并返回，以防目标 API 返回的不是标准 OpenAI 格式
		bodyBytes, _ := io.ReadAll(resp.Body)
		// 重新构造一个 reader 用于后续可能的处理，这里简单返回解析失败
		resp.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
		logger.Error(ctx, "解析目标 API 响应失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "解析目标 API 响应失败"})
		return
	}

	// 提取模型列表
	var models []map[string]string
	for _, m := range fetchResp.Data {
		models = append(models, map[string]string{"id": m.ID, "name": m.ID})
	}

	writeJSON(w, http.StatusOK, response{Code: 0, Msg: "success", Data: models})
}

// HandleDeletePreset 删除预设
func (h *ApiConfigPresetHandler) HandleDeletePreset(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	id := r.PathValue("id")
	if id == "" {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "缺少预设 ID"})
		return
	}

	preset, err := h.repo.GetByID(ctx, id)
	if err != nil || preset == nil {
		writeJSON(w, http.StatusNotFound, response{Code: 404, Msg: "预设不存在"})
		return
	}

	if preset.IsActive {
		writeJSON(w, http.StatusBadRequest, response{Code: 400, Msg: "不能删除当前激活的预设"})
		return
	}

	if err := h.repo.Delete(ctx, id); err != nil {
		logger.Error(ctx, "删除预设失败", zap.Error(err))
		writeJSON(w, http.StatusInternalServerError, response{Code: 500, Msg: "删除预设失败"})
		return
	}

	writeJSON(w, http.StatusOK, response{Code: 0, Msg: "success"})
}

// 辅助方法：加密模型配置
func (h *ApiConfigPresetHandler) encryptModelConfig(cfg ModelConfig) (string, error) {
	if cfg.APIKey != "" && cfg.APIKey != "********" {
		encrypted, err := h.cryptoSvc.Encrypt(cfg.APIKey)
		if err != nil {
			return "", err
		}
		cfg.APIKey = encrypted
	}
	bytes, err := json.Marshal(cfg)
	return string(bytes), err
}

// 辅助方法：解密模型配置为 Proto 结构
func (h *ApiConfigPresetHandler) decryptToProtoModelConfig(jsonStr string) (*pb.ModelConfig, error) {
	var cfg ModelConfig
	if err := json.Unmarshal([]byte(jsonStr), &cfg); err != nil {
		return nil, err
	}
	if cfg.APIKey != "" {
		decrypted, err := h.cryptoSvc.Decrypt(cfg.APIKey)
		if err == nil {
			cfg.APIKey = decrypted
		}
	}
	return &pb.ModelConfig{
		BaseUrl:     cfg.BaseURL,
		ApiKey:      cfg.APIKey,
		ModelId:          cfg.ModelID,
		MaxTokens:        cfg.MaxTokens,
		MaxContextTokens: cfg.MaxContextTokens,
		Temperature:      cfg.Temperature,
	}, nil
}

// 辅助方法：转换为前端响应结构（脱敏）
func (h *ApiConfigPresetHandler) toPresetResponse(p repository.ApiConfigPreset) PresetResponse {
	var large, medium, small ModelConfig
	json.Unmarshal([]byte(p.LargeModelConfig), &large)
	json.Unmarshal([]byte(p.MediumModelConfig), &medium)
	json.Unmarshal([]byte(p.SmallModelConfig), &small)

	if large.APIKey != "" {
		large.APIKey = "********"
	}
	if medium.APIKey != "" {
		medium.APIKey = "********"
	}
	if small.APIKey != "" {
		small.APIKey = "********"
	}

	return PresetResponse{
		ID:                p.ID,
		Name:              p.Name,
		IsActive:          p.IsActive,
		LargeModelConfig:  large,
		MediumModelConfig: medium,
		SmallModelConfig:  small,
	}
}
