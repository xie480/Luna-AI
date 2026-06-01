package infrastructure

import (
	"context"
	"fmt"
	"time"

	"luna-ai/backend/runtime/internal/logger"
)

// QdrantCollection 定义 Qdrant 集合常量
// 长期记忆向量集合：存储每日会话摘要的 Embedding，用于语义检索
const QdrantCollectionLongTermMemories = "luna_long_term_memories"

// QdrantSearchResult 定义 Qdrant 搜索结果结构
type QdrantSearchResult struct {
	ID      string                 `json:"id"`
	Score   float64                `json:"score"`
	Payload map[string]interface{} `json:"payload"`
}

// QdrantClient 封装 Qdrant 向量数据库客户端
// 做什么：提供向量 Upsert、Search、Delete 等操作的统一接口
// 为什么这样做：Qdrant 作为本地轻量化向量数据库，用于长期记忆的语义检索
type QdrantClient struct {
	// 使用 HTTP API 与 Qdrant 交互
	baseURL    string
	httpClient *HttpClient
}

// NewQdrantClient 创建一个新的 QdrantClient 实例
// 参数：
//   - baseURL: Qdrant HTTP API 地址，例如 http://localhost:6333
//
// 返回：*QdrantClient, error
func NewQdrantClient(baseURL string) (*QdrantClient, error) {
	if baseURL == "" {
		baseURL = "http://localhost:6333"
	}
	client := &QdrantClient{
		baseURL:    baseURL,
		httpClient: NewHttpClient(10 * time.Second),
	}

	// 测试连接
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.ping(ctx); err != nil {
		logger.Warn(ctx, "Qdrant 连接测试失败，将使用降级模式", "base_url", baseURL, "error", err)
	} else {
		logger.Info(ctx, "Qdrant 连接成功", "base_url", baseURL)
	}

	return client, nil
}

// ping 测试 Qdrant 连接是否可用
func (c *QdrantClient) ping(ctx context.Context) error {
	url := fmt.Sprintf("%s/collections", c.baseURL)
	_, err := c.httpClient.Get(ctx, url)
	return err
}

// EnsureCollection 确保集合存在，不存在则创建
// 向量维度默认为 1536（OpenAI text-embedding-ada-002 的维度）
func (c *QdrantClient) EnsureCollection(ctx context.Context, collectionName string, vectorSize int) error {
	// 先检查集合是否存在
	exists, err := c.collectionExists(ctx, collectionName)
	if err != nil {
		return fmt.Errorf("检查 Qdrant 集合失败: %w", err)
	}
	if exists {
		logger.Info(ctx, "Qdrant 集合已存在", "collection", collectionName)
		return nil
	}

	// 创建集合
	url := fmt.Sprintf("%s/collections/%s", c.baseURL, collectionName)
	body := CreateCollectionBody{
		Vectors: CreateCollectionVectors{
			Size:     vectorSize,
			Distance: "Cosine",
		},
	}
	_, err = c.httpClient.Put(ctx, url, body)
	if err != nil {
		return fmt.Errorf("创建 Qdrant 集合失败: %w", err)
	}
	logger.Info(ctx, "Qdrant 集合已创建", "collection", collectionName, "vector_size", vectorSize)
	return nil
}

// CreateCollectionBody 创建集合请求体
type CreateCollectionBody struct {
	Vectors CreateCollectionVectors `json:"vectors"`
}

// CreateCollectionVectors 向量配置
type CreateCollectionVectors struct {
	Size     int    `json:"size"`
	Distance string `json:"distance"`
}

// collectionExists 检查集合是否存在
func (c *QdrantClient) collectionExists(ctx context.Context, collectionName string) (bool, error) {
	url := fmt.Sprintf("%s/collections/%s", c.baseURL, collectionName)
	resp, err := c.httpClient.Get(ctx, url)
	if err != nil {
		return false, nil // 如果请求失败，视为不存在
	}
	return resp != nil && resp.Status == "ok", nil
}

// UpsertRequest 单个向量点请求
type UpsertPoint struct {
	ID      string                 `json:"id"`
	Vector  []float64              `json:"vector"`
	Payload map[string]interface{} `json:"payload"`
}

// UpsertBody Upsert 请求体
type UpsertBody struct {
	Points []UpsertPoint `json:"points"`
}

// Upsert 插入或更新向量点
// 输入：
//   - ctx: 上下文
//   - collectionName: 集合名称
//   - points: 要插入的向量点列表
//
// 输出：error
func (c *QdrantClient) Upsert(ctx context.Context, collectionName string, points []UpsertPoint) error {
	if len(points) == 0 {
		return nil
	}

	url := fmt.Sprintf("%s/collections/%s/points", c.baseURL, collectionName)
	body := UpsertBody{Points: points}

	_, err := c.httpClient.Upsert(ctx, url, body)
	if err != nil {
		return fmt.Errorf("Qdrant Upsert 失败 [collection=%s]: %w", collectionName, err)
	}

	logger.Info(ctx, "Qdrant Upsert 成功", "collection", collectionName, "count", len(points))
	return nil
}

// SearchBody 搜索请求体
type SearchBody struct {
	Vector     []float64 `json:"vector"`
	Limit      int       `json:"limit"`
	WithPayload bool     `json:"with_payload"`
}

// SearchResponse 搜索响应
type SearchResponse struct {
	Result []QdrantSearchResult `json:"result"`
}

// Search 执行向量相似度搜索
// 输入：
//   - ctx: 上下文
//   - collectionName: 集合名称
//   - vector: 查询向量
//   - topK: 返回 Top-K 结果
//
// 输出：[]QdrantSearchResult, error
func (c *QdrantClient) Search(ctx context.Context, collectionName string, vector []float64, topK int) ([]QdrantSearchResult, error) {
	url := fmt.Sprintf("%s/collections/%s/points/search", c.baseURL, collectionName)
	body := SearchBody{
		Vector:      vector,
		Limit:       topK,
		WithPayload: true,
	}

	resp, err := c.httpClient.Search(ctx, url, body)
	if err != nil {
		return nil, fmt.Errorf("Qdrant Search 失败 [collection=%s]: %w", collectionName, err)
	}

	if resp == nil || resp.Result == nil {
		return nil, nil
	}

	// 将 Result 解析为 SearchResponse
	var searchResp SearchResponse
	if err := resp.DecodeJSON(&searchResp); err != nil {
		return nil, fmt.Errorf("解析 Qdrant Search 响应失败: %w", err)
	}

	logger.Info(ctx, "Qdrant Search 完成", "collection", collectionName, "hits", len(searchResp.Result))
	return searchResp.Result, nil
}

// DeletePointsBody 删除请求体
type DeletePointsBody struct {
	Points []string `json:"points"`
}

// DeletePoints 删除指定 ID 的向量点
// 输入：
//   - ctx: 上下文
//   - collectionName: 集合名称
//   - ids: 要删除的点 ID 列表
//
// 输出：error
func (c *QdrantClient) DeletePoints(ctx context.Context, collectionName string, ids []string) error {
	if len(ids) == 0 {
		return nil
	}

	url := fmt.Sprintf("%s/collections/%s/points/delete", c.baseURL, collectionName)
	body := DeletePointsBody{Points: ids}

	_, err := c.httpClient.Delete(ctx, url, body)
	if err != nil {
		return fmt.Errorf("Qdrant DeletePoints 失败 [collection=%s]: %w", collectionName, err)
	}

	logger.Info(ctx, "Qdrant DeletePoints 完成", "collection", collectionName, "count", len(ids))
	return nil
}

// IsHealthy 检查 Qdrant 连接健康状态
func (c *QdrantClient) IsHealthy(ctx context.Context) bool {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return c.ping(ctx) == nil
}
