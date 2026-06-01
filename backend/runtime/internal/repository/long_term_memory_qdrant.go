package repository

import (
	"context"
	"fmt"

	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
)

// LongTermMemoryQdrantRepo 封装 Qdrant 中长期记忆的向量检索操作
// 做什么：提供记忆摘要的向量 Upsert、检索和删除操作
// 为什么这样做：Qdrant 作为语义检索引擎，通过向量相似度快速定位相关的历史记忆
type LongTermMemoryQdrantRepo struct {
	client *infrastructure.QdrantClient
}

// NewLongTermMemoryQdrantRepo 创建 LongTermMemoryQdrantRepo 实例
func NewLongTermMemoryQdrantRepo(client *infrastructure.QdrantClient) *LongTermMemoryQdrantRepo {
	return &LongTermMemoryQdrantRepo{client: client}
}

// EnsureCollection 确保长期记忆集合存在
// 向量维度：1536（默认与 OpenAI text-embedding-ada-002 对齐）
func (r *LongTermMemoryQdrantRepo) EnsureCollection(ctx context.Context, vectorSize int) error {
	return r.client.EnsureCollection(ctx, infrastructure.QdrantCollectionLongTermMemories, vectorSize)
}

// SaveWithVector 保存长期记忆向量
// 输入：
//   - ctx: 上下文
//   - memoryID: 记忆 ID（对应 PG 表的主键）
//   - sessionID: 会话 ID
//   - vector: 记忆摘要的 Embedding 向量
//   - status: 记忆状态（MemoryStatusActive / MemoryStatusDeleted）
//
// 输出：error
func (r *LongTermMemoryQdrantRepo) SaveWithVector(ctx context.Context, memoryID string, sessionID string, vector []float64, status MemoryStatus) error {
	if status == "" {
		status = MemoryStatusActive
	}
	point := infrastructure.UpsertPoint{
		ID:     memoryID,
		Vector: vector,
		Payload: map[string]interface{}{
			"session_id": sessionID,
			"status":     string(status),
		},
	}
	if err := r.client.Upsert(ctx, infrastructure.QdrantCollectionLongTermMemories, []infrastructure.UpsertPoint{point}); err != nil {
		return fmt.Errorf("保存长期记忆向量失败 [memory_id=%s]: %w", memoryID, err)
	}
	logger.Info(ctx, "长期记忆向量已保存", "memory_id", memoryID, "session_id", sessionID)
	return nil
}

// SearchByVector 根据向量检索长期记忆
// 输入：
//   - ctx: 上下文
//   - vector: 查询向量
//   - topK: 返回 Top-K 结果
//
// 输出：[]QdrantSearchResult, error
// 边界条件：仅返回 payload 中 status=MemoryStatusActive 的记录需要在业务层过滤
func (r *LongTermMemoryQdrantRepo) SearchByVector(ctx context.Context, vector []float64, topK int) ([]infrastructure.QdrantSearchResult, error) {
	results, err := r.client.Search(ctx, infrastructure.QdrantCollectionLongTermMemories, vector, topK)
	if err != nil {
		return nil, fmt.Errorf("检索长期记忆向量失败: %w", err)
	}

	// 过滤掉 status!=MemoryStatusActive 的结果
	activeStatus := string(MemoryStatusActive)
	activeResults := make([]infrastructure.QdrantSearchResult, 0, len(results))
	for _, result := range results {
		if status, ok := result.Payload["status"].(string); ok && status == activeStatus {
			activeResults = append(activeResults, result)
		}
	}

	logger.Info(ctx, "长期记忆向量检索完成", "hits", len(activeResults), "top_k", topK)
	return activeResults, nil
}

// SoftDeleteByMemoryID 根据记忆 ID 软删除向量（更新 payload 中的 status）
func (r *LongTermMemoryQdrantRepo) SoftDeleteByMemoryID(ctx context.Context, memoryID string) error {
	// Qdrant 不支持直接修改 payload 中单个字段，需重新 Upsert
	// 使用空向量 + MemoryStatusDeleted 状态覆盖
	point := infrastructure.UpsertPoint{
		ID: memoryID,
		// 使用零值向量覆盖：后续搜索时不会被匹配到（余弦相似度极低）
		Vector: make([]float64, 1536),
		Payload: map[string]interface{}{
			"status": string(MemoryStatusDeleted),
		},
	}
	if err := r.client.Upsert(ctx, infrastructure.QdrantCollectionLongTermMemories, []infrastructure.UpsertPoint{point}); err != nil {
		return fmt.Errorf("软删除长期记忆向量失败 [memory_id=%s]: %w", memoryID, err)
	}
	logger.Info(ctx, "长期记忆向量已软删除", "memory_id", memoryID)
	return nil
}
