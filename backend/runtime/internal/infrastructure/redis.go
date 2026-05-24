package infrastructure

import (
	"context"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"

	"luna-ai/backend/runtime/internal/logger"
)

// RedisClient 封装 Redis 客户端连接
// 用于 DAG 工作流毫秒级状态同步与 Event Bus
type RedisClient struct {
	// Redis 客户端实例
	client *redis.Client
}

// NewRedisClient 创建一个新的 RedisClient 实例
// 参数:
//   - addr: Redis 服务器地址，格式为 host:port
//   - password: Redis 密码，本地开发通常为空
//   - db: Redis 数据库编号
// 返回:
//   - *RedisClient: Redis 客户端实例
//   - error: 连接错误信息
func NewRedisClient(addr, password string, db int) (*RedisClient, error) {
	// 创建 Redis 客户端配置
	client := redis.NewClient(&redis.Options{
		Addr:     addr,     // Redis 服务器地址
		Password: password, // Redis 密码
		DB:       db,       // Redis 数据库编号
	})

	// 测试连接是否可用
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("Redis 连接失败: %w", err)
	}

	logger.Info(context.Background(), "Redis 连接成功", zap.String("addr", addr), zap.Int("db", db))

	return &RedisClient{
		client: client,
	}, nil
}

// Close 关闭 Redis 连接
// 在服务关闭时调用，释放连接资源
func (r *RedisClient) Close() error {
	if r.client != nil {
		return r.client.Close()
	}
	return nil
}

// Ping 测试 Redis 连接是否可用
// 用于健康检查
func (r *RedisClient) Ping(ctx context.Context) error {
	return r.client.Ping(ctx).Err()
}

// GetClient 获取原始 Redis 客户端实例
// 用于执行具体的 Redis 操作
func (r *RedisClient) GetClient() *redis.Client {
	return r.client
}

// IsHealthy 检查 Redis 连接健康状态
// 返回 true 表示连接正常，false 表示连接异常
func (r *RedisClient) IsHealthy(ctx context.Context) bool {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return r.client.Ping(ctx).Err() == nil
}