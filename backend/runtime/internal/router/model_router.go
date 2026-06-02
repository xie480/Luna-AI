package router

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	"luna-ai/backend/runtime/internal/repository"
)

// NodeType 定义交互节点类型
type NodeType string

const (
	// NodeChat 聊天交互节点
	NodeChat NodeType = "chat"
	// NodeSummarize 摘要压缩交互节点
	NodeSummarize NodeType = "summarize"
)

// ModelSize 定义模型规格标识
type ModelSize string

const (
	// ModelSizeBig 大模型（对应复杂推理/聊天）
	ModelSizeBig ModelSize = "big"
	// ModelSizeSmall 小模型（对应后台摘要/分类）
	ModelSizeSmall ModelSize = "small"
	// ModelSizeMedium 中模型（备用）
	ModelSizeMedium ModelSize = "medium"
)

// ModelConfig 模型配置实例（内存缓存结构）
type ModelConfig struct {
	BaseURL     string  `json:"base_url"`
	APIKey      string  `json:"api_key"`
	ModelID          string  `json:"model_id"`
	MaxTokens        int32   `json:"max_tokens"`
	MaxContextTokens int32   `json:"max_context_tokens"`
	Temperature      float32 `json:"temperature"`
}

// ModelRouter 模型路由与缓存加载模块
// 做什么：负责根据节点类型路由到对应的模型规格，并提供带防击穿机制的内存缓存。
// 为什么这样做：提高模型配置的读取性能，解耦节点逻辑与底层模型配置，支持动态扩展节点和模型映射。
type ModelRouter struct {
	// nodeToSizeMap 节点到模型规格的映射字典
	nodeToSizeMap map[NodeType]ModelSize
	
	// cache 内存缓存，用于存储已加载的模型配置
	// key: ModelSize, value: *ModelConfig
	cache sync.Map 
	
	// presetRepo 预设配置仓库，作为模型库的数据源
	presetRepo *repository.ConfigPresetPGRepo
	
	// singleflight 用于保护缓存的并发更新（防止缓存击穿）
	// key: ModelSize, value: *sync.Mutex
	singleflight sync.Map 
}

// NewModelRouter 创建模型路由实例
func NewModelRouter(repo *repository.ConfigPresetPGRepo) *ModelRouter {
	return &ModelRouter{
		nodeToSizeMap: map[NodeType]ModelSize{
			NodeChat:      ModelSizeBig,
			NodeSummarize: ModelSizeSmall,
		},
		presetRepo: repo,
	}
}

// RegisterNode 动态注册或更新节点路由映射（提供良好的扩展性）
func (r *ModelRouter) RegisterNode(nodeType NodeType, size ModelSize) {
	r.nodeToSizeMap[nodeType] = size
}

// ClearCache 清空指定规格或所有缓存（用于配置更新时）
func (r *ModelRouter) ClearCache(size *ModelSize) {
	if size != nil {
		r.cache.Delete(*size)
	} else {
		r.cache.Range(func(key, value any) bool {
			r.cache.Delete(key)
			return true
		})
	}
}

// GetModelForNode 根据节点类型路由并获取对应的模型配置
// 输入：ctx 上下文, nodeType 节点类型
// 输出：目标模型配置指针, 错误信息
func (r *ModelRouter) GetModelForNode(ctx context.Context, nodeType NodeType) (*ModelConfig, error) {
	// 1. 查询映射字典获取对应的模型标识
	size, exists := r.nodeToSizeMap[nodeType]
	if !exists {
		return nil, fmt.Errorf("未知的交互节点类型: %s", nodeType)
	}

	// 2. 尝试从内存缓存中获取（缓存命中）
	if cached, ok := r.cache.Load(size); ok {
		return cached.(*ModelConfig), nil
	}

	// 3. 缓存缺失，处理并发读取情况（防止缓存击穿）
	// 获取或创建该 size 对应的互斥锁
	muIface, _ := r.singleflight.LoadOrStore(size, &sync.Mutex{})
	mu := muIface.(*sync.Mutex)
	
	mu.Lock()
	defer mu.Unlock()

	// 再次检查缓存（双重检查锁定 DCL）
	if cached, ok := r.cache.Load(size); ok {
		return cached.(*ModelConfig), nil
	}

	// 4. 从模型库（数据库）中安全地检索出目标模型的配置
	config, err := r.fetchConfigFromDB(ctx, size)
	if err != nil {
		return nil, fmt.Errorf("从模型库获取配置失败: %w", err)
	}

	// 5. 将其加载到内存缓存中以便当前和后续操作快速调用
	r.cache.Store(size, config)

	return config, nil
}

// fetchConfigFromDB 从数据库获取当前激活的预设，并提取对应规格的配置
func (r *ModelRouter) fetchConfigFromDB(ctx context.Context, size ModelSize) (*ModelConfig, error) {
	activePreset, err := r.presetRepo.GetActive(ctx)
	if err != nil {
		return nil, err
	}
	if activePreset == nil {
		return nil, fmt.Errorf("当前没有激活的 API 配置预设")
	}

	var configJSON string
	switch size {
	case ModelSizeBig:
		configJSON = activePreset.LargeModelConfig
	case ModelSizeMedium:
		configJSON = activePreset.MediumModelConfig
	case ModelSizeSmall:
		configJSON = activePreset.SmallModelConfig
	default:
		return nil, fmt.Errorf("不支持的模型规格: %s", size)
	}

	var config ModelConfig
	if err := json.Unmarshal([]byte(configJSON), &config); err != nil {
		return nil, fmt.Errorf("解析模型配置 JSON 失败: %w", err)
	}

	return &config, nil
}
