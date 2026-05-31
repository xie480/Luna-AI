package config

import (
	"context"
	"encoding/json"
	"fmt"
	"sync/atomic"

	"luna-ai/backend/runtime/internal/repository"
)

// ConfigPresetRepo 定义配置预设仓储接口
type ConfigPresetRepo interface {
	GetActive(ctx context.Context) (*repository.ApiConfigPreset, error)
	GetByID(ctx context.Context, id string) (*repository.ApiConfigPreset, error)
	SetActive(ctx context.Context, id string) error
}

// ActiveConfigSnapshot 存储当前激活配置的内存快照
type ActiveConfigSnapshot struct {
	PresetID          string
	LargeModelConfig  ModelConfig
	MediumModelConfig ModelConfig
	SmallModelConfig  ModelConfig
}

// ModelConfig 定义模型配置的 JSON 结构
type ModelConfig struct {
	BaseURL     string  `json:"base_url"`
	APIKey      string  `json:"api_key"`
	ModelID     string  `json:"model_id"`
	MaxTokens   int32   `json:"max_tokens"`
	Temperature float32 `json:"temperature"`
}

// Manager 负责动态配置的管理、热更新与内存快照
type Manager struct {
	repo      ConfigPresetRepo
	cryptoSvc *CryptoService
	eventBus  *EventBus
	
	// activeConfig 存储 *ActiveConfigSnapshot
	activeConfig atomic.Value
}

// NewManager 创建 ConfigManager
func NewManager(repo ConfigPresetRepo, cryptoSvc *CryptoService, eventBus *EventBus) *Manager {
	m := &Manager{
		repo:      repo,
		cryptoSvc: cryptoSvc,
		eventBus:  eventBus,
	}
	// 初始化一个空的快照
	m.activeConfig.Store(&ActiveConfigSnapshot{})
	return m
}

// LoadActiveConfig 从数据库加载当前激活的配置到内存快照
func (m *Manager) LoadActiveConfig(ctx context.Context) error {
	preset, err := m.repo.GetActive(ctx)
	if err != nil {
		return fmt.Errorf("获取激活预设失败: %w", err)
	}
	if preset == nil {
		return nil // 没有激活的预设
	}

	snapshot, err := m.buildSnapshot(preset)
	if err != nil {
		return fmt.Errorf("构建配置快照失败: %w", err)
	}

	m.activeConfig.Store(snapshot)
	return nil
}

// GetActiveConfig 获取当前激活配置的内存快照（无锁读取）
func (m *Manager) GetActiveConfig() *ActiveConfigSnapshot {
	return m.activeConfig.Load().(*ActiveConfigSnapshot)
}

// ActivatePreset 激活指定的预设，更新内存快照，并发布配置变更事件
func (m *Manager) ActivatePreset(ctx context.Context, id string) error {
	// 1. 更新数据库激活状态
	if err := m.repo.SetActive(ctx, id); err != nil {
		return fmt.Errorf("设置激活状态失败: %w", err)
	}

	// 2. 获取完整预设数据
	preset, err := m.repo.GetByID(ctx, id)
	if err != nil || preset == nil {
		return fmt.Errorf("获取预设数据失败: %w", err)
	}

	// 3. 构建新的内存快照
	snapshot, err := m.buildSnapshot(preset)
	if err != nil {
		return fmt.Errorf("构建配置快照失败: %w", err)
	}

	// 4. 更新内存快照
	m.activeConfig.Store(snapshot)

	// 5. 发布配置变更事件
	m.eventBus.Publish(Event{
		Type: EventConfigChanged,
		Data: snapshot,
	})

	return nil
}

// buildSnapshot 将数据库模型转换为内存快照，并解密 API Key
func (m *Manager) buildSnapshot(preset *repository.ApiConfigPreset) (*ActiveConfigSnapshot, error) {
	large, err := m.decryptModelConfig(preset.LargeModelConfig)
	if err != nil {
		return nil, err
	}
	medium, err := m.decryptModelConfig(preset.MediumModelConfig)
	if err != nil {
		return nil, err
	}
	small, err := m.decryptModelConfig(preset.SmallModelConfig)
	if err != nil {
		return nil, err
	}

	return &ActiveConfigSnapshot{
		PresetID:          preset.ID,
		LargeModelConfig:  large,
		MediumModelConfig: medium,
		SmallModelConfig:  small,
	}, nil
}

// decryptModelConfig 解密模型配置中的 API Key
func (m *Manager) decryptModelConfig(jsonStr string) (ModelConfig, error) {
	var cfg ModelConfig
	if err := json.Unmarshal([]byte(jsonStr), &cfg); err != nil {
		return cfg, err
	}
	if cfg.APIKey != "" {
		decrypted, err := m.cryptoSvc.Decrypt(cfg.APIKey)
		if err == nil {
			cfg.APIKey = decrypted
		}
	}
	return cfg, nil
}
