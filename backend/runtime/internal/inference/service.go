package inference

import (
	"context"
	"encoding/json"
	"fmt"

	"luna-ai/backend/runtime/internal/logger"
	pb "luna-ai/backend/runtime/shared/proto"
)

// AIClient 定义了推理服务所需的 AI 客户端接口
type AIClient interface {
	Embedding(ctx context.Context, req *pb.EmbeddingRequest) (*pb.EmbeddingResponse, error)
	Rerank(ctx context.Context, req *pb.RerankRequest) (*pb.RerankResponse, error)
}

// Service 定义了通用的推理服务接口
// 做什么：抽象 Embedding 和 Rerank 等模型推理能力，使其与具体业务逻辑解耦
// 为什么这样做：便于在项目的其他模块（如知识库检索、意图识别等）中复用这些基础能力
type Service interface {
	// GetEmbeddingVector 获取文本的语义向量
	GetEmbeddingVector(ctx context.Context, text string) ([]float64, error)

	// RerankDocuments 对候选文档进行相关性重排
	// 返回排序后的文档索引和对应的分数
	RerankDocuments(ctx context.Context, query string, documents []string) ([]RerankResult, error)
}

// RerankResult 表示单个文档的重排结果
type RerankResult struct {
	Index int     // 文档在原始列表中的索引
	Score float64 // 相关性分数
}

// serviceImpl 是 Service 接口的默认实现，基于 gRPC 调用 Python AI 服务
type serviceImpl struct {
	aiClient AIClient
}

// NewService 创建一个新的推理服务实例
func NewService(aiClient AIClient) Service {
	return &serviceImpl{
		aiClient: aiClient,
	}
}

// GetEmbeddingVector 获取文本的语义向量
// 做什么：调用 Python AI 服务的 Embedding 方法，将文本编码为稠密向量
// 输入：
//   - ctx: 上下文
//   - text: 需要向量化的文本
//
// 输出：[]float64（语义向量）, error
// 边界条件：
//   - text 为空时返回错误
//   - aiClient 不可用时返回错误
func (s *serviceImpl) GetEmbeddingVector(ctx context.Context, text string) ([]float64, error) {
	if s.aiClient == nil {
		return nil, fmt.Errorf("AI 客户端不可用，无法获取向量")
	}

	if text == "" {
		return nil, fmt.Errorf("需要向量化的文本不能为空")
	}

	req := &pb.EmbeddingRequest{
		Text: text,
	}

	resp, err := s.aiClient.Embedding(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("Embedding 调用失败: %w", err)
	}

	if !resp.Success {
		return nil, fmt.Errorf("Embedding 返回错误: %s", resp.ErrorMessage)
	}

	// 解析 JSON 格式的向量字符串
	vector, err := parseVectorFromJSON(resp.VectorJson)
	if err != nil {
		return nil, fmt.Errorf("解析向量 JSON 失败: %w", err)
	}

	if len(vector) == 0 {
		return nil, fmt.Errorf("Embedding 返回空向量")
	}

	return vector, nil
}

// parseVectorFromJSON 解析 JSON 格式的 float64 向量字符串
func parseVectorFromJSON(jsonStr string) ([]float64, error) {
	if jsonStr == "" || jsonStr == "[]" {
		return nil, fmt.Errorf("向量 JSON 为空")
	}

	var vector []float64
	if err := json.Unmarshal([]byte(jsonStr), &vector); err != nil {
		return nil, fmt.Errorf("向量 JSON 反序列化失败: %w", err)
	}

	return vector, nil
}

// RerankDocuments 对候选文档进行相关性重排
// 做什么：调用 Python AI 服务的 Rerank 方法，计算查询与候选文档的相关性分数，并按分数降序排列
// 输入：
//   - ctx: 上下文
//   - query: 查询文本
//   - documents: 候选文档列表
//
// 输出：[]RerankResult（按分数降序排列）, error
func (s *serviceImpl) RerankDocuments(ctx context.Context, query string, documents []string) ([]RerankResult, error) {
	if s.aiClient == nil {
		return nil, fmt.Errorf("AI 客户端不可用，无法进行重排")
	}

	if query == "" {
		return nil, fmt.Errorf("查询文本不能为空")
	}

	if len(documents) == 0 {
		return []RerankResult{}, nil
	}

	req := &pb.RerankRequest{
		Query:     query,
		Documents: documents,
	}

	resp, err := s.aiClient.Rerank(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("Rerank 调用失败: %w", err)
	}

	if !resp.Success {
		return nil, fmt.Errorf("Rerank 返回错误: %s", resp.ErrorMessage)
	}

	if len(resp.Scores) != len(documents) {
		return nil, fmt.Errorf("Rerank 返回分数数量不匹配: 期望 %d, 实际 %d", len(documents), len(resp.Scores))
	}

	// 构造结果并排序
	results := make([]RerankResult, len(documents))
	for i, score := range resp.Scores {
		results[i] = RerankResult{
			Index: i,
			Score: score,
		}
	}

	// 插入排序（降序）
	for i := 1; i < len(results); i++ {
		key := results[i]
		j := i - 1
		for j >= 0 && results[j].Score < key.Score {
			results[j+1] = results[j]
			j--
		}
		results[j+1] = key
	}

	logger.Info(ctx, "Rerank 重排完成", "文档数", len(documents), "最高分", results[0].Score)
	return results, nil
}
