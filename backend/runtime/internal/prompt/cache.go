package prompt

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
	"golang.org/x/sync/singleflight"

	"luna-ai/backend/runtime/internal/logger"
)

const (
	// cacheKeyPrefix 缓存键前缀
	cacheKeyPrefix = "luna:prompt:"
	// cacheTTL 缓存过期时间（1小时）
	cacheTTL = 1 * time.Hour
	// cacheEmptyTTL 空结果缓存过期时间（1分钟，防止缓存穿透）
	cacheEmptyTTL = 1 * time.Minute
)

// CachedPrompt 缓存中的 Prompt 模板结构
type CachedPrompt struct {
	SystemContent  string `json:"system_content"`
	MemoryContent  string `json:"memory_content"`
	RuntimeContent string `json:"runtime_content"`
}

// CacheManager 实现基于 Redis 的 Prompt 懒加载缓存
// 职责：
//   - 首次访问时从 PostgreSQL 加载并缓存到 Redis
//   - 后续访问直接读取 Redis 缓存
//   - 使用 singleflight 防止缓存击穿
type CacheManager struct {
	rdb         *redis.Client
	pgRepo      PromptRepository
	singleGroup *singleflight.Group
}

// NewCacheManager 创建缓存管理器
func NewCacheManager(rdb *redis.Client, pgRepo PromptRepository) *CacheManager {
	return &CacheManager{
		rdb:         rdb,
		pgRepo:      pgRepo,
		singleGroup: &singleflight.Group{},
	}
}

// cacheKey 构建缓存键
func cacheKey(category PromptCategory) string {
	return cacheKeyPrefix + string(category)
}

// GetOrLoad 从缓存获取，缓存未命中时从数据库加载
// 使用 singleflight 防止缓存击穿：同一时刻对同一个 category 的并发请求只会有一个穿透到数据库
func (cm *CacheManager) GetOrLoad(ctx context.Context, category PromptCategory) (*CachedPrompt, error) {
	// 1. 尝试从 Redis 读取
	if cm.rdb != nil {
		cached, err := cm.rdb.Get(ctx, cacheKey(category)).Result()
		if err == nil {
			var cp CachedPrompt
			if jsonErr := json.Unmarshal([]byte(cached), &cp); jsonErr == nil {
				logger.Info(ctx, "从 Redis 缓存获取 Prompt 成功", zap.String("category", string(category)))
				return &cp, nil
			}
		} else if err != redis.Nil {
			// Redis 错误不是 key 不存在，记录警告
			logger.Warn(ctx, "Redis 读取 Prompt 缓存失败", zap.String("category", string(category)), zap.Error(err))
		}
	}

	// 2. 使用 singleflight 防止缓存击穿
	result, err, _ := cm.singleGroup.Do(cacheKey(category), func() (interface{}, error) {
		return cm.loadFromDB(ctx, category)
	})
	if err != nil {
		return nil, err
	}

	cp := result.(*CachedPrompt)

	// 3. 写入 Redis 缓存（异步写入，不阻塞主流程）
	if cm.rdb != nil {
		go func() {
			data, jsonErr := json.Marshal(cp)
			if jsonErr != nil {
				return
			}
			ttl := cacheTTL
			// 如果所有内容都为空，使用更短的 TTL 防止缓存穿透
			if cp.SystemContent == "" && cp.MemoryContent == "" && cp.RuntimeContent == "" {
				ttl = cacheEmptyTTL
			}
			if setErr := cm.rdb.Set(ctx, cacheKey(category), string(data), ttl).Err(); setErr != nil {
				logger.Warn(ctx, "写入 Prompt 缓存到 Redis 失败", zap.String("category", string(category)), zap.Error(setErr))
			}
		}()
	}

	return cp, nil
}

// loadFromDB 从 PostgreSQL 加载指定分类的模板，按 SlotPosition 分类提取内容
func (cm *CacheManager) loadFromDB(ctx context.Context, category PromptCategory) (*CachedPrompt, error) {
	templates, err := cm.pgRepo.GetTemplatesByCategory(ctx, string(category))
	if err != nil {
		return nil, fmt.Errorf("加载分类 %s 的模板失败: %w", category, err)
	}

	cp := &CachedPrompt{}

	for _, tmpl := range templates {
		if tmpl.ActiveVersionID == "" {
			continue
		}

		version, err := cm.pgRepo.GetVersion(ctx, tmpl.ActiveVersionID)
		if err != nil {
			logger.Warn(ctx, "获取模板版本失败，跳过", zap.String("template_name", tmpl.Name), zap.Error(err))
			continue
		}

		switch SlotPosition(tmpl.SlotPosition) {
		case SlotSystem:
			cp.SystemContent = version.Content
		case SlotMemory:
			cp.MemoryContent = version.Content
		case SlotRuntime:
			cp.RuntimeContent = version.Content
		default:
			logger.Warn(ctx, "未知的 SlotPosition 值", zap.String("slot_position", tmpl.SlotPosition))
		}
	}

	logger.Info(ctx, "从数据库加载 Prompt 模板成功",
		zap.String("category", string(category)),
		zap.Bool("has_system", cp.SystemContent != ""),
		zap.Bool("has_memory", cp.MemoryContent != ""),
		zap.Bool("has_runtime", cp.RuntimeContent != ""))

	return cp, nil
}

// InvalidateCache 使指定分类的缓存失效
func (cm *CacheManager) InvalidateCache(ctx context.Context, category PromptCategory) error {
	if cm.rdb != nil {
		if err := cm.rdb.Del(ctx, cacheKey(category)).Err(); err != nil {
			return fmt.Errorf("清除 Prompt 缓存失败: %w", err)
		}
		logger.Info(ctx, "已清除 Prompt 缓存", zap.String("category", string(category)))
	}
	return nil
}

// GetAssembledPrompt 获取并组装完整的 Prompt 字符串
// 使用固定占位符模板 {system}\n\n{memory}\n\n{runtime}
// 将各 slot 的模板内容注入到对应的占位符位置
// 最终将未被注入的占位符替换为空字符串
func (cm *CacheManager) GetAssembledPrompt(ctx context.Context, category PromptCategory, variables map[string]string) (string, error) {
	cp, err := cm.GetOrLoad(ctx, category)
	if err != nil {
		return "", err
	}

	// 准备固定占位符模板
	fullText := PlaceholderSystem + "\n\n" + PlaceholderMemory + "\n\n" + PlaceholderRuntime

	// 按照标准顺序注入模板内容
	slotContents := map[string]string{
		PlaceholderSystem:  cp.SystemContent,
		PlaceholderMemory:  cp.MemoryContent,
		PlaceholderRuntime: cp.RuntimeContent,
	}

	result := fullText
	for _, placeholder := range SlotPlaceholders {
		content := slotContents[placeholder]
		if content != "" {
			// 对模板内容进行变量替换
				rendered := renderTemplate(content, variables)
			result = strings.ReplaceAll(result, placeholder, rendered)
		}
	}

	return result, nil
}
