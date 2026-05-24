package api

import (
	"context"
	"fmt"
	"time"

	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"luna-ai/backend/runtime/internal/logger"
	pb "luna-ai/backend/runtime/shared/proto"
)

// AIClient 封装了与 Python AI 服务的 gRPC 通信
type AIClient struct {
	// gRPC 连接
	conn *grpc.ClientConn
	// gRPC 客户端
	client pb.CommunicationServiceClient
}

// NewAIClient 创建一个新的 AIClient 实例
func NewAIClient(address string) (*AIClient, error) {
	// 建立 gRPC 连接
	conn, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to AI service: %w", err)
	}

	// 创建 gRPC 客户端
	client := pb.NewCommunicationServiceClient(conn)

	logger.Info(context.Background(), "成功连接到 AI 服务", zap.String("address", address))

	return &AIClient{
		conn:   conn,
		client: client,
	}, nil
}

// Close 关闭 gRPC 连接
func (c *AIClient) Close() error {
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// Ping 发送 Ping 请求到 AI 服务
func (c *AIClient) Ping(ctx context.Context, traceID string) (*pb.PongResponse, error) {
	req := &pb.PingRequest{
		TraceId:   traceID,
		Timestamp: time.Now().UnixMilli(),
	}

	logger.Info(ctx, "发送 Ping 请求到 AI 服务", zap.String("trace_id", traceID), zap.Int64("timestamp", req.Timestamp))

	// 设置超时时间
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	resp, err := c.client.Ping(ctx, req)
	if err != nil {
		logger.Error(ctx, "Ping 请求失败", zap.String("trace_id", traceID), zap.Error(err))
		return nil, fmt.Errorf("ping failed: %w", err)
	}

	logger.Info(ctx, "收到 AI 服务的 Pong 响应", zap.String("trace_id", traceID), zap.Int64("timestamp", resp.Timestamp), zap.String("source", resp.Source))
	return resp, nil
}
