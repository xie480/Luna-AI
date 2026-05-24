package infrastructure

import (
	"context"
	"fmt"
	"time"

	"go.uber.org/zap"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"

	"luna-ai/backend/runtime/internal/logger"
)

// PostgresClient 封装 PostgreSQL 客户端连接
// 用于配置、记忆、状态持久化存储
type PostgresClient struct {
	// GORM 数据库实例
	db *gorm.DB
}

// NewPostgresClient 创建一个新的 PostgresClient 实例
// 参数:
//   - connStr: PostgreSQL 连接字符串，格式为 postgres://user:password@host:port/database
//
// 返回:
//   - *PostgresClient: PostgreSQL 客户端实例
//   - error: 连接错误信息
func NewPostgresClient(connStr string) (*PostgresClient, error) {
	// 配置 GORM 连接参数
	gormConfig := &gorm.Config{
		// 禁用默认事务，提升性能
		SkipDefaultTransaction: true,
		// 准备语句缓存
		PrepareStmt: true,
	}

	// 建立 PostgreSQL 连接
	db, err := gorm.Open(postgres.Open(connStr), gormConfig)
	if err != nil {
		return nil, fmt.Errorf("PostgreSQL 连接失败: %w", err)
	}

	// 获取底层 sql.DB 并配置连接池
	sqlDB, err := db.DB()
	if err != nil {
		return nil, fmt.Errorf("获取数据库连接池失败: %w", err)
	}

	// 配置连接池参数
	// 最大空闲连接数
	sqlDB.SetMaxIdleConns(10)
	// 最大打开连接数
	sqlDB.SetMaxOpenConns(100)
	// 连接最大存活时间
	sqlDB.SetConnMaxLifetime(time.Hour)

	// 测试连接是否可用
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := sqlDB.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("PostgreSQL Ping 测试失败: %w", err)
	}

	logger.Info(context.Background(), "PostgreSQL 连接成功", zap.String("connection_string", maskPassword(connStr)))

	return &PostgresClient{
		db: db,
	}, nil
}

// Close 关闭 PostgreSQL 连接
// 在服务关闭时调用，释放连接资源
func (p *PostgresClient) Close() error {
	if p.db != nil {
		sqlDB, err := p.db.DB()
		if err != nil {
			return err
		}
		return sqlDB.Close()
	}
	return nil
}

// Ping 测试 PostgreSQL 连接是否可用
// 用于健康检查
func (p *PostgresClient) Ping(ctx context.Context) error {
	sqlDB, err := p.db.DB()
	if err != nil {
		return err
	}
	return sqlDB.PingContext(ctx)
}

// GetDB 获取 GORM 数据库实例
// 用于执行具体的数据库操作
func (p *PostgresClient) GetDB() *gorm.DB {
	return p.db
}

// IsHealthy 检查 PostgreSQL 连接健康状态
// 返回 true 表示连接正常，false 表示连接异常
func (p *PostgresClient) IsHealthy(ctx context.Context) bool {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return p.Ping(ctx) == nil
}

// maskPassword 隐藏连接字符串中的密码
// 用于日志输出，防止敏感信息泄露
func maskPassword(connStr string) string {
	// 简单的密码隐藏逻辑，将 password=xxx 替换为 password=[REDACTED]
	// 格式: postgres://user:password@host:port/database
	if len(connStr) > 0 {
		// 查找 :// 和 @ 之间的部分
		start := "postgres://"
		if len(connStr) > len(start) {
			rest := connStr[len(start):]
			// 查找 @ 符号位置
			atIndex := -1
			for i, c := range rest {
				if c == '@' {
					atIndex = i
					break
				}
			}
			if atIndex > 0 {
				// 查找 : 符号位置（用户名和密码之间）
				colonIndex := -1
				for i, c := range rest[:atIndex] {
					if c == ':' {
						colonIndex = i
						break
					}
				}
				if colonIndex > 0 {
					// 隐藏密码部分
					return start + rest[:colonIndex+1] + "[REDACTED]" + rest[atIndex:]
				}
			}
		}
	}
	return connStr
}
