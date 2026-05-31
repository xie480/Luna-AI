package api

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"

	"luna-ai/backend/runtime/internal/logger"
	"luna-ai/backend/runtime/internal/telemetry"
	"luna-ai/backend/runtime/internal/utils/snowflake"
	pb "luna-ai/backend/runtime/shared/proto"
)

// AIClient 封装了与 Python AI 服务的 gRPC 通信
type AIClient struct {
	// gRPC 连接
	conn *grpc.ClientConn
	// gRPC 客户端
	client pb.CommunicationServiceClient
}

// TelemetryUnaryClientInterceptor gRPC 客户端拦截器
// 自动从 context 提取 TraceID 注入 gRPC Metadata，并记录调用 Span。
func TelemetryUnaryClientInterceptor() grpc.UnaryClientInterceptor {
	return func(ctx context.Context, method string, req, reply interface{},
		cc *grpc.ClientConn, invoker grpc.UnaryInvoker, opts ...grpc.CallOption) error {

		traceID, _ := ctx.Value(logger.TraceIDKey).(string)
		if traceID == "" {
			traceID = snowflake.GenerateStringID()
		}
		spanID := snowflake.GenerateStringID()

		// 将 TraceID 和 ParentSpanID 注入 gRPC Metadata
		md := metadata.Pairs("x-trace-id", traceID, "x-parent-span-id", spanID)
		ctx = metadata.NewOutgoingContext(ctx, md)

		startTime := time.Now()
		err := invoker(ctx, method, req, reply, cc, opts...)
		duration := time.Since(startTime)

		status := "OK"
		if err != nil {
			status = "ERROR"
		}

		// 异步记录 Span
		if worker := telemetry.GetWorker(); worker != nil {
			worker.RecordSpanAsync(&telemetry.TraceSpan{
				TraceID:      traceID,
				SpanID:       spanID,
				Name:         method,
				Service:      "go_runtime",
				StartTime:    startTime,
				EndTime:      time.Now(),
				DurationMs:   duration.Milliseconds(),
				Status:       status,
				Attributes:   "{}", // 可以根据 reply 提取更多属性
			})
		}

		return err
	}
}

// TelemetryStreamClientInterceptor gRPC 客户端流拦截器
func TelemetryStreamClientInterceptor() grpc.StreamClientInterceptor {
	return func(ctx context.Context, desc *grpc.StreamDesc, cc *grpc.ClientConn, method string, streamer grpc.Streamer, opts ...grpc.CallOption) (grpc.ClientStream, error) {
		traceID, _ := ctx.Value(logger.TraceIDKey).(string)
		if traceID == "" {
			traceID = snowflake.GenerateStringID()
		}
		spanID := snowflake.GenerateStringID()

		md := metadata.Pairs("x-trace-id", traceID, "x-parent-span-id", spanID)
		ctx = metadata.NewOutgoingContext(ctx, md)

		startTime := time.Now()
		clientStream, err := streamer(ctx, desc, cc, method, opts...)
		
		// 注意：流式调用的耗时记录比较复杂，这里只记录流建立的耗时
		// 实际的流处理耗时需要在业务层记录
		duration := time.Since(startTime)
		status := "OK"
		if err != nil {
			status = "ERROR"
		}

		if worker := telemetry.GetWorker(); worker != nil {
			worker.RecordSpanAsync(&telemetry.TraceSpan{
				TraceID:      traceID,
				SpanID:       spanID,
				Name:         method + "_stream_init",
				Service:      "go_runtime",
				StartTime:    startTime,
				EndTime:      time.Now(),
				DurationMs:   duration.Milliseconds(),
				Status:       status,
				Attributes:   "{}",
			})
		}

		return clientStream, err
	}
}

// NewAIClient 创建一个新的 AIClient 实例
func NewAIClient(address string) (*AIClient, error) {
	// 建立 gRPC 连接，注入拦截器
	conn, err := grpc.NewClient(address, 
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(TelemetryUnaryClientInterceptor()),
		grpc.WithStreamInterceptor(TelemetryStreamClientInterceptor()),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to AI service: %w", err)
	}

	// 创建 gRPC 客户端
	client := pb.NewCommunicationServiceClient(conn)

	logger.Info(context.Background(), "成功连接到 AI 服务", "address", address)

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

	logger.Info(ctx, "发送 Ping 请求到 AI 服务", "trace_id", traceID, "timestamp", req.Timestamp)

	// 设置超时时间
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	resp, err := c.client.Ping(ctx, req)
	if err != nil {
		logger.Error(ctx, "Ping 请求失败", "trace_id", traceID, "error", err)
		return nil, fmt.Errorf("ping failed: %w", err)
	}

	logger.Info(ctx, "收到 AI 服务的 Pong 响应", "trace_id", traceID, "timestamp", resp.Timestamp, "source", resp.Source)
	return resp, nil
}

// ChatStream 发送流式对话请求到 AI 服务
func (c *AIClient) ChatStream(ctx context.Context, req *pb.ChatRequest) (pb.CommunicationService_ChatStreamClient, error) {
	logger.Info(ctx, "发送 ChatStream 请求到 AI 服务", "trace_id", req.TraceId)

	stream, err := c.client.ChatStream(ctx, req)
	if err != nil {
		logger.Error(ctx, "ChatStream 请求失败", "trace_id", req.TraceId, "error", err)
		return nil, fmt.Errorf("chat stream failed: %w", err)
	}

	return stream, nil
}

// SummarizeContext 发送摘要压缩请求到 AI 服务
func (c *AIClient) SummarizeContext(ctx context.Context, req *pb.SummarizeContextRequest) (*pb.SummarizeContextResponse, error) {
	logger.Info(ctx, "发送 SummarizeContext 请求到 AI 服务", "trace_id", req.TraceId)

	// 设置超时时间，摘要压缩可能需要较长时间
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	resp, err := c.client.SummarizeContext(ctx, req)
	if err != nil {
		logger.Error(ctx, "SummarizeContext 请求失败", "trace_id", req.TraceId, "error", err)
		return nil, fmt.Errorf("summarize context failed: %w", err)
	}

	return resp, nil
}

// SyncPresetConfig 发送预设配置同步请求到 AI 服务
func (c *AIClient) SyncPresetConfig(ctx context.Context, req *pb.SyncPresetConfigRequest) (*pb.SyncPresetConfigResponse, error) {
	logger.Info(ctx, "发送 SyncPresetConfig 请求到 AI 服务", "preset_id", req.PresetId)

	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	resp, err := c.client.SyncPresetConfig(ctx, req)
	if err != nil {
		logger.Error(ctx, "SyncPresetConfig 请求失败", "preset_id", req.PresetId, "error", err)
		return nil, fmt.Errorf("sync preset config failed: %w", err)
	}

	return resp, nil
}
