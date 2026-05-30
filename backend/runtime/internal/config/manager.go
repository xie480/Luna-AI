package config

import (
	"context"
	"fmt"
	"sync/atomic"

	"go.uber.org/zap"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
)

// AppConfig 动态配置的内存快照
type AppConfig struct {
	LLMAPIKey string
	// 可以添加其他动态配置项
}

// ConfigManager 负责动态配置的热更新与内存快照
type ConfigManager struct {
	configRepo *repository.ConfigPGRepo
	cryptoSvc  *CryptoService
	eventBus   *EventBus
	current    atomic.Value // 存储 *AppConfig
}

// NewConfigManager 创建 ConfigManager
func NewConfigManager(repo *repository.ConfigPGRepo, cryptoSvc *CryptoService, eventBus *EventBus) (*ConfigManager, error) {
	cm := &ConfigManager{
		configRepo: repo,
		cryptoSvc:  cryptoSvc,
		eventBus:   eventBus,
	}
	
	// 初始化一个空的配置
	cm.current.Store(&AppConfig{})

	// 从数据库加载配置
	if err := cm.loadFromDB(context.Background()); err != nil {
		return nil, err
	}

	return cm, nil
}

// GetConfig 无锁读取当前配置的内存快照
func (cm *ConfigManager) GetConfig() *AppConfig {
	return cm.current.Load().(*AppConfig)
}

// loadFromDB 从数据库加载配置并更新内存快照
func (cm *ConfigManager) loadFromDB(ctx context.Context) error {
	configs, err := cm.configRepo.GetAll(ctx)
	if err != nil {
		return err
	}

	newConfig := &AppConfig{}
	for _, cfg := range configs {
		val := cfg.Value
		if cfg.IsEncrypted {
			decrypted, err := cm.cryptoSvc.Decrypt(val)
			if err != nil {
				return fmt.Errorf("解密配置项 %s 失败: %w", cfg.Key, err)
			}
			val = decrypted
		}

		switch cfg.Key {
		case "llm_api_key":
			newConfig.LLMAPIKey = val
		}
	}

	cm.current.Store(newConfig)
	return nil
}

// UpdateConfig 接收更新，识别敏感字段并加密，落盘至 PostgreSQL，更新内存快照，并通过 EventBus 广播
func (cm *ConfigManager) UpdateConfig(ctx context.Context, updates map[string]interface{}) error {
	for key, val := range updates {
		strVal, ok := val.(string)
		if !ok {
			continue // 暂时只处理字符串类型的配置
		}

		isEncrypted := false
		if key == "llm_api_key" {
			isEncrypted = true
			encryptedVal, err := cm.cryptoSvc.Encrypt(strVal)
			if err != nil {
				return fmt.Errorf("加密配置项 %s 失败: %w", key, err)
			}
			strVal = encryptedVal
		}

		sysConfig := &repository.SystemConfig{
			ID:          snowflake.GenerateStringID(),
			Key:         key,
			Value:       strVal,
			IsEncrypted: isEncrypted,
		}

		if err := cm.configRepo.Save(ctx, sysConfig); err != nil {
			return err
		}
	}

	// 重新加载到内存
	if err := cm.loadFromDB(ctx); err != nil {
		return err
	}

	// 广播事件
	cm.eventBus.Publish(Event{
		Type: ConfigChangedEvent,
		Data: cm.GetConfig(),
	})

	// 记录审计日志
	logger.Info(ctx, "配置已更新", zap.Any("keys", getKeys(updates)))

	return nil
}

func getKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
