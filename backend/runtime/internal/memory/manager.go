package memory

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"luna-ai/backend/runtime/internal/infrastructure"
	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/prompt"
	"luna-ai/backend/runtime/internal/repository"
	"luna-ai/backend/runtime/internal/utils/snowflake"
	pb "luna-ai/backend/runtime/shared/proto"
)

// MemoryEventType 定义记忆系统事件类型
type MemoryEventType string

const (
	// EventMemorySync 长期记忆同步事件：通知前端记忆面板已更新
	EventMemorySync MemoryEventType = "EVT_MEMORY_SYNC"
)

// MemoryEvent 记忆系统事件
type MemoryEvent struct {
	Type    MemoryEventType
	Payload interface{}
}

// MemoryEventHandler 记忆事件处理函数
type MemoryEventHandler func(event MemoryEvent)

// AIClient 定义 AI 客户端接口，用于与 Python AI 服务通信
type AIClient interface {
	// CompressHistory 调用 Python 的 CompressHistory gRPC 方法
	CompressHistory(ctx context.Context, req *pb.CompressHistoryRequest) (*pb.CompressHistoryResponse, error)

	// Embedding 调用 Python 的 Embedding 方法进行文本向量化
	// 做什么：将自然语言文本转换为稠密向量，用于 Qdrant 语义检索
	// 输入输出：
	//   - 输入：EmbeddingRequest {text}
	//   - 输出：EmbeddingResponse {vector_json, success, error_message}
	// 边界条件：text 为空时返回 success=false
	Embedding(ctx context.Context, req *pb.EmbeddingRequest) (*pb.EmbeddingResponse, error)

	// Rerank 调用 Python 的 Rerank 方法进行文档相关性重排
	// 做什么：计算查询与候选文档的相关性分数
	// 输入输出：
	//   - 输入：RerankRequest {query, documents[]}
	//   - 输出：RerankResponse {scores[], success, error_message}
	// 边界条件：query 为空时返回 success=false
	Rerank(ctx context.Context, req *pb.RerankRequest) (*pb.RerankResponse, error)

	// Ping 健康检查
	Ping(ctx context.Context, traceID string) (*pb.PongResponse, error)
}

// Manager 长期记忆管理器
// 做什么：协调长期记忆的完整生命周期：会话流转检测、历史压缩、双库提交、记忆检索
// 为什么这样做：Go Runtime 是唯一调度权威，所有记忆写入必须经过此管理器的事务控制
type Manager struct {
	// 仓库依赖
	redisRepo     *repository.ChatHistoryRedisRepo
	ltmPGRepo     *repository.LongTermMemoryPGRepo
	ltmQdrantRepo *repository.LongTermMemoryQdrantRepo

	// AI 客户端接口（用于调用 CompressHistory gRPC）
	aiClient AIClient

	// Prompt 管理器（用于组装 compress_history 提示词）
	promptMgr *prompt.Manager

	// Qdrant 客户端（用于直接操作集合）
	qdrantClient *infrastructure.QdrantClient

	// 事件监听器
	listeners []MemoryEventHandler
	mu        sync.RWMutex

	// 是否启用记忆同步通知
	enableSyncNotify bool
}

// NewManager 创建长期记忆管理器
// 参数：
//   - redisRepo: Redis 仓库（读取历史会话数据）
//   - ltmPGRepo: PG 长期记忆仓库（写入记忆记录）
//   - ltmQdrantRepo: Qdrant 长期记忆仓库（写入向量）
//   - aiClient: AI 客户端（调用压缩服务）
//   - promptMgr: Prompt 管理器（组装提示词）
//   - qdrantClient: Qdrant 客户端（初始化集合）
func NewManager(
	redisRepo *repository.ChatHistoryRedisRepo,
	ltmPGRepo *repository.LongTermMemoryPGRepo,
	ltmQdrantRepo *repository.LongTermMemoryQdrantRepo,
	aiClient AIClient,
	promptMgr *prompt.Manager,
	qdrantClient *infrastructure.QdrantClient,
) *Manager {
	return &Manager{
		redisRepo:        redisRepo,
		ltmPGRepo:        ltmPGRepo,
		ltmQdrantRepo:    ltmQdrantRepo,
		aiClient:         aiClient,
		promptMgr:        promptMgr,
		qdrantClient:     qdrantClient,
		enableSyncNotify: true,
	}
}

// OnEvent 注册记忆事件监听器
func (m *Manager) OnEvent(handler MemoryEventHandler) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.listeners = append(m.listeners, handler)
}

// emit 触发记忆事件
func (m *Manager) emit(event MemoryEvent) {
	m.mu.RLock()
	listeners := make([]MemoryEventHandler, len(m.listeners))
	copy(listeners, m.listeners)
	m.mu.RUnlock()

	for _, handler := range listeners {
		handler(event)
	}
}

// Init 初始化长期记忆系统
// 做什么：
//  1. 确保 Qdrant 集合存在
//  2. 执行启动时兜底检测：清理 Redis 中的非当日历史会话
//
// 输入：
//   - ctx: 上下文
//
// 输出：error
func (m *Manager) Init(ctx context.Context) error {
	logger.Info(ctx, "正在初始化长期记忆系统")

	// 1. 确保 Qdrant 集合存在（默认向量维度 1536）
	if m.qdrantClient != nil && m.ltmQdrantRepo != nil {
		if err := m.ltmQdrantRepo.EnsureCollection(ctx, 1536); err != nil {
			logger.Warn(ctx, "Qdrant 集合初始化失败，将使用降级模式", "error", err)
		}
	}

	// 2. 执行启动时兜底检测
	if err := m.detectAndCleanupHistoricalSessions(ctx); err != nil {
		logger.Error(ctx, "启动时兜底检测执行失败", "error", err)
		// 不阻断启动，允许降级
	}

	logger.Info(ctx, "长期记忆系统初始化完成")
	return nil
}

// detectAndCleanupHistoricalSessions 启动时兜底检测
// 做什么：扫描 Redis 中非今日的历史会话数据，执行压缩入库后删除 Redis 数据
// 为什么这样做：桌面程序可能被随时关闭，防止历史会话数据残留导致内存泄漏或重复处理
func (m *Manager) detectAndCleanupHistoricalSessions(ctx context.Context) error {
	if m.redisRepo == nil {
		logger.Warn(ctx, "Redis 不可用，跳过启动时兜底检测")
		return nil
	}

	today := time.Now().Format("20060102")
	logger.Info(ctx, "执行启动时兜底检测", "today", today)

	sessionIDs, err := m.redisRepo.GetAllSessionIDs(ctx)
	if err != nil {
		return fmt.Errorf("获取 Redis 中所有会话 ID 失败: %w", err)
	}

	processedCount := 0
	for _, sessionID := range sessionIDs {
		if sessionID == today {
			continue
		}

		logger.Info(ctx, "发现非当日历史会话，准备压缩入库", "session_id", sessionID)

		if err := m.compressAndCommit(ctx, sessionID); err != nil {
			logger.Error(ctx, "历史会话压缩入库失败，保留 Redis 数据等待下次重试", "session_id", sessionID, "error", err)
			continue
		}

		if err := m.redisRepo.DeleteSession(ctx, sessionID); err != nil {
			logger.Error(ctx, "删除 Redis 历史会话数据失败", "session_id", sessionID, "error", err)
		} else {
			logger.Info(ctx, "已从 Redis 中删除历史会话数据", "session_id", sessionID)
		}

		processedCount++
	}

	logger.Info(ctx, "启动时兜底检测完成", "processed_count", processedCount, "today", today)
	return nil
}

// compressAndCommit 压缩历史会话并提交到双库
// 做什么：
//  1. 从 Redis 提取历史会话的完整上下文（summary + history）
//  2. 调用 Python CompressHistory gRPC 进行 AI 压缩
//  3. 写入 PG 长期记忆记录
//  4. 同步写入 Qdrant 向量
func (m *Manager) compressAndCommit(ctx context.Context, sessionID string) error {
	traceID := snowflake.GenerateStringID()
	logger.Info(ctx, "开始压缩历史会话", "session_id", sessionID, "trace_id", traceID)

	summary, history, err := m.redisRepo.GetContext(ctx, sessionID)
	if err != nil {
		return fmt.Errorf("从 Redis 获取会话上下文失败 [session_id=%s]: %w", sessionID, err)
	}

	if len(history) == 0 {
		logger.Info(ctx, "会话无历史记录，跳过压缩", "session_id", sessionID)
		return nil
	}

	var contextBuilder strings.Builder
	contextBuilder.WriteString(fmt.Sprintf("会话摘要:\n%s\n\n关键事实:\n%s\n\n历史对话:\n", summary.CoreSummary, summary.KeyFacts))
	for i, h := range history {
		contextBuilder.WriteString(fmt.Sprintf("[对话 %d]\n", i+1))
		contextBuilder.WriteString(fmt.Sprintf("用户: %s\n", h.UserContent))
		contextBuilder.WriteString(fmt.Sprintf("Luna: %s\n", h.AssistantContent))
		if h.Thought != "" {
			contextBuilder.WriteString(fmt.Sprintf("(内心独白: %s)\n", h.Thought))
		}
		if h.Emotion != "" {
			contextBuilder.WriteString(fmt.Sprintf("(心情: %s)\n", h.Emotion))
		}
		contextBuilder.WriteString("\n")
	}
	sessionContext := contextBuilder.String()

	if m.aiClient == nil {
		return fmt.Errorf("AI 客户端不可用，无法压缩历史会话 [session_id=%s]", sessionID)
	}

	compressReq := &pb.CompressHistoryRequest{
		SessionId:      sessionID,
		SessionContext: sessionContext,
	}

	compressResp, err := m.aiClient.CompressHistory(ctx, compressReq)
	if err != nil {
		return fmt.Errorf("调用 CompressHistory 失败 [session_id=%s]: %w", sessionID, err)
	}

	compressedSummary := strings.TrimSpace(compressResp.Summary)
	if compressedSummary == "" {
		return fmt.Errorf("CompressHistory 返回空摘要 [session_id=%s]", sessionID)
	}

	logger.Info(ctx, "历史会话压缩完成", "session_id", sessionID, "summary_length", len(compressedSummary))

	memoryID := snowflake.GenerateStringID()
	now := time.Now()

	// 5. 保存到 PostgreSQL（使用枚举常量定义状态）
	memory := &repository.LongTermMemory{
		ID:        memoryID,
		SessionID: sessionID,
		Summary:   compressedSummary,
		Status:    repository.MemoryStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
	}

	if err := m.ltmPGRepo.Save(ctx, memory); err != nil {
		return fmt.Errorf("保存长期记忆到 PostgreSQL 失败 [session_id=%s]: %w", sessionID, err)
	}

	// 6. 对压缩后的摘要进行向量化，写入 Qdrant 向量库
	if m.ltmQdrantRepo != nil {
		// 调用 AI 服务的 Embedding 方法获取真实向量
		embeddingVec, embedErr := m.getEmbeddingVector(ctx, compressedSummary)
		if embedErr != nil {
			logger.Warn(ctx, "获取语义向量失败，使用零值向量写入 Qdrant（后续可对账补充）", "memory_id", memoryID, "error", embedErr)
			embeddingVec = make([]float64, 1536)
		}

		if err := m.ltmQdrantRepo.SaveWithVector(ctx, memoryID, sessionID, embeddingVec, repository.MemoryStatusActive); err != nil {
			logger.Warn(ctx, "Qdrant 向量写入失败", "memory_id", memoryID, "error", err)
		} else {
			logger.Info(ctx, "长期记忆向量写入成功", "memory_id", memoryID, "vector_dim", len(embeddingVec))
		}
	}

	logger.Info(ctx, "长期记忆提交完成", "session_id", sessionID, "memory_id", memoryID)

	// 7. 触发记忆同步事件（使用枚举常量）
	if m.enableSyncNotify {
		m.emit(MemoryEvent{
			Type: EventMemorySync,
			Payload: map[string]interface{}{
				"session_id": sessionID,
				"memory_id":  memoryID,
				"status":     string(repository.MemoryStatusActive),
			},
		})
	}

	return nil
}

// RolloverSession 执行自然日会话流转
// 做什么：当系统时间跨过午夜（00:00）时，将当前活跃会话切换为第二天的会话，
//
//	并触发前一天的会话压缩入库流程。
//
// 输入：
//   - ctx: 上下文
//   - currentSessionID: 当前会话 ID（YYYYMMDD 格式）
//
// 输出：string（新的会话 ID）, error
func (m *Manager) RolloverSession(ctx context.Context, currentSessionID string) (string, error) {
	today := time.Now().Format("20060102")

	if currentSessionID == today {
		return currentSessionID, nil
	}

	logger.Info(ctx, "执行自然日会话流转", "old_session", currentSessionID, "new_session", today)

	if currentSessionID != "" {
		if err := m.compressAndCommit(ctx, currentSessionID); err != nil {
			logger.Error(ctx, "会话流转压缩入库失败", "session_id", currentSessionID, "error", err)
		}

		if m.redisRepo != nil {
			if err := m.redisRepo.DeleteSession(ctx, currentSessionID); err != nil {
				logger.Warn(ctx, "删除 Redis 旧会话数据失败", "session_id", currentSessionID, "error", err)
			}
		}
	}

	return today, nil
}

// getEmbeddingVector 获取文本的语义向量
// 做什么：调用 Python AI 服务的 Embedding 方法，将文本编码为稠密向量
// 为什么这样做：作为统一的向量化入口，确保所有文本向量化都经过 AI 服务
// 输入：
//   - ctx: 上下文
//   - text: 需要向量化的文本
//
// 输出：[]float64（语义向量）, error
// 边界条件：
//   - text 为空时返回错误
//   - aiClient 不可用时返回错误
// 异常行为：
//   - Embedding 响应中 success=false 时返回错误
//   - vector_json 解析失败时返回错误
func (m *Manager) getEmbeddingVector(ctx context.Context, text string) ([]float64, error) {
	if m.aiClient == nil {
		return nil, fmt.Errorf("AI 客户端不可用，无法获取向量")
	}

	req := &pb.EmbeddingRequest{
		Text: text,
	}

	resp, err := m.aiClient.Embedding(ctx, req)
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
// 做什么：将 `"[0.123, 0.456, ...]"` 格式的 JSON 字符串解析为 []float64
// 为什么这样做：Protobuf 不支持直接传输 float64 数组，使用 JSON 序列化传输
// 输入：
//   - jsonStr: JSON 格式的向量字符串
//
// 输出：[]float64, error
// 边界条件：jsonStr 为空时返回空切片
func parseVectorFromJSON(jsonStr string) ([]float64, error) {
	if jsonStr == "" || jsonStr == "[]" {
		return nil, fmt.Errorf("向量 JSON 为空")
	}

	// 使用 encoding/json 解析
	var vector []float64
	if err := json.Unmarshal([]byte(jsonStr), &vector); err != nil {
		return nil, fmt.Errorf("向量 JSON 反序列化失败: %w", err)
	}

	return vector, nil
}

// RetrieveLongTermMemories 检索长期记忆（带语义检索与重排）
// 做什么：根据用户意图查询文本，先通过 Embedding 转为向量进行 Qdrant 粗排检索，
//         再通过 CrossEncoder 精排提升 Top-K 结果的排序质量
//
// 流程：
//  1. 如果提供了 queryText，先调用 Embedding 转为查询向量
//  2. 从 Qdrant 检索 Top-K * 3（粗排候选数）相关的记忆 ID
//  3. 从 PostgreSQL 拉取完整的记忆内容
//  4. 如果提供了 queryText 且 aiClient 支持 Rerank，对结果进行重排精排
//
// 输入：
//   - ctx: 上下文
//   - queryText: 查询文本（用户意图），用于 Embedding 向量化和 Rerank 重排
//   - queryVector: 预计算的查询向量（如果 queryText 为空时使用此向量，或两者都为空则仅查询）
//   - topK: 返回 Top-K 结果
//
// 输出：[]LongTermMemory（完整记忆记录）, error
// 边界条件：
//   - Qdrant 或 PG 不可用时降级为空返回
//   - queryText 和 queryVector 都为空时仅返回最近记忆
//   - Rerank 不可用时仅使用 Qdrant 粗排结果
func (m *Manager) RetrieveLongTermMemories(ctx context.Context, queryText string, queryVector []float64, topK int) ([]repository.LongTermMemory, error) {
	if m.ltmQdrantRepo == nil || m.ltmPGRepo == nil {
		logger.Warn(ctx, "长期记忆系统不可用，跳过记忆检索")
		return nil, nil
	}

	if topK <= 0 {
		topK = 5
	}

	// 如果提供了 queryText，先通过 Embdedding 转为查询向量（覆盖外部传入的 queryVector）
	finalQueryVector := queryVector
	if queryText != "" && m.aiClient != nil {
		embeddingVec, err := m.getEmbeddingVector(ctx, queryText)
		if err != nil {
			logger.Warn(ctx, "获取查询向量的 Embedding 失败，使用外部传入向量（如有）", "error", err)
		} else {
			finalQueryVector = embeddingVec
		}
	}

	// 如果仍然没有向量，无法进行语义检索，返回空
	if len(finalQueryVector) == 0 {
		logger.Warn(ctx, "查询向量为空，跳过语义检索")
		return nil, nil
	}

	// Qdrant 粗排：检索 Top-K 的 3 倍候选数，为后续重排提供足够候选
	searchTopK := topK * 3
	if searchTopK > 50 {
		searchTopK = 50 // 限制最大候选数，防止性能问题
	}

	results, err := m.ltmQdrantRepo.SearchByVector(ctx, finalQueryVector, searchTopK)
	if err != nil {
		logger.Warn(ctx, "Qdrant 向量检索失败，降级为空返回", "error", err)
		return nil, nil
	}

	if len(results) == 0 {
		logger.Info(ctx, "Qdrant 无匹配结果", "top_k", topK)
		return nil, nil
	}

	memoryIDs := make([]string, 0, len(results))
	for _, result := range results {
		memoryIDs = append(memoryIDs, result.ID)
	}

	memories, err := m.ltmPGRepo.GetByIDs(ctx, memoryIDs)
	if err != nil {
		logger.Warn(ctx, "从 PG 拉取记忆记录失败，降级为空返回", "error", err)
		return nil, nil
	}

	if len(memories) == 0 {
		return nil, nil
	}

	// Rerank 精排：如果提供了 queryText，且 AI 客户端支持 Rerank，对结果进行重排
	if queryText != "" && m.aiClient != nil && len(memories) > 1 {
		rerankMemories, rerankErr := m.rerankMemories(ctx, queryText, memories, topK)
		if rerankErr != nil {
			// Rerank 失败时降级为粗排结果，截取 topK
			logger.Warn(ctx, "Rerank 重排失败，使用 Qdrant 粗排结果", "error", rerankErr)
			if len(memories) > topK {
				memories = memories[:topK]
			}
		} else {
			memories = rerankMemories
		}
	} else if len(memories) > topK {
		// 没有 Rerank 时，截取前 topK 个
		memories = memories[:topK]
	}

	logger.Info(ctx, "长期记忆检索完成", "hits", len(memories), "top_k", topK, "has_rerank", queryText != "" && m.aiClient != nil)
	return memories, nil
}

// rerankMemories 使用 CrossEncoder 对候选记忆进行重排
// 做什么：调用 Python AI 服务的 Rerank 方法，对 queryText 和候选记忆的 Summary 进行相关性打分，
//         按分数降序排列后返回 Top-K 结果
// 为什么这样做：Qdrant 的向量相似度（余弦/点积）是粗排，CrossEncoder 精排能显著提升结果质量
// 输入：
//   - ctx: 上下文
//   - queryText: 查询文本（用户意图）
//   - memories: 候选记忆列表
//   - topK: 返回 Top-K 结果
//
// 输出：[]repository.LongTermMemory（按相关性降序排列）, error
// 边界条件：
//   - aiClient 为 nil 时返回原始列表
//   - Rerank 失败时返回原始列表
// 异常行为：
//   - Rerank 响应中 success=false 时返回 error
//   - scores 长度与 memories 长度不一致时返回 error
func (m *Manager) rerankMemories(ctx context.Context, queryText string, memories []repository.LongTermMemory, topK int) ([]repository.LongTermMemory, error) {
	if m.aiClient == nil {
		return memories, nil
	}

	// 提取候选文档列表（使用记忆的 Summary 作为文档内容）
	documents := make([]string, len(memories))
	for i, mem := range memories {
		documents[i] = mem.Summary
	}

	req := &pb.RerankRequest{
		Query:     queryText,
		Documents: documents,
	}

	resp, err := m.aiClient.Rerank(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("Rerank 调用失败: %w", err)
	}

	if !resp.Success {
		return nil, fmt.Errorf("Rerank 返回错误: %s", resp.ErrorMessage)
	}

	if len(resp.Scores) != len(memories) {
		return nil, fmt.Errorf("Rerank 返回分数数量不匹配: 期望 %d, 实际 %d", len(memories), len(resp.Scores))
	}

	// 按分数对 memories 进行降序排列
	type scoredMemory struct {
		memory repository.LongTermMemory
		score  float64
	}

	scored := make([]scoredMemory, len(memories))
	for i, mem := range memories {
		scored[i] = scoredMemory{memory: mem, score: resp.Scores[i]}
	}

	// 使用 Go 1.21+ 的 slices 排序或简单冒泡排序
	// 这里使用插入排序（简单且适合小规模数据）
	for i := 1; i < len(scored); i++ {
		key := scored[i]
		j := i - 1
		for j >= 0 && scored[j].score < key.score {
			scored[j+1] = scored[j]
			j--
		}
		scored[j+1] = key
	}

	// 提取排序后的记忆列表，截取 topK
	result := make([]repository.LongTermMemory, 0, min(topK, len(scored)))
	for i := 0; i < min(topK, len(scored)); i++ {
		result = append(result, scored[i].memory)
	}

	logger.Info(ctx, "Rerank 重排完成", "原始数", len(memories), "返回数", len(result), "最高分", scored[0].score)
	return result, nil
}
