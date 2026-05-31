package telemetry

import (
	"sync"
	"time"
)

// MetricPoint 监控数据点
type MetricPoint struct {
	Timestamp           time.Time `json:"timestamp"`
	SystemCPUUsage      float64   `json:"system_cpu_usage"`
	SystemMemoryUsage   float64   `json:"system_memory_usage"`
	GoGoroutinesCount   int       `json:"go_goroutines_count"`
	LLMTokenConsumption int       `json:"llm_token_consumption"`
	ToolCallFailureRate float64   `json:"tool_call_failure_rate"`
}

// RingBuffer 环形缓冲区，用于存储最近的监控指标
type RingBuffer struct {
	mu       sync.RWMutex
	data     []MetricPoint
	capacity int
	head     int
	count    int
}

// NewRingBuffer 创建一个新的环形缓冲区
func NewRingBuffer(capacity int) *RingBuffer {
	return &RingBuffer{
		data:     make([]MetricPoint, capacity),
		capacity: capacity,
		head:     0,
		count:    0,
	}
}

// Push 添加一个新的数据点
func (rb *RingBuffer) Push(point MetricPoint) {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	rb.data[rb.head] = point
	rb.head = (rb.head + 1) % rb.capacity
	if rb.count < rb.capacity {
		rb.count++
	}
}

// GetRecent 获取最近的 n 个数据点，按时间正序排列
func (rb *RingBuffer) GetRecent(n int) []MetricPoint {
	rb.mu.RLock()
	defer rb.mu.RUnlock()

	if n > rb.count {
		n = rb.count
	}
	if n == 0 {
		return []MetricPoint{}
	}

	result := make([]MetricPoint, n)
	
	// 计算起始读取位置
	start := (rb.head - n + rb.capacity) % rb.capacity
	
	for i := 0; i < n; i++ {
		idx := (start + i) % rb.capacity
		result[i] = rb.data[idx]
	}

	return result
}

// 全局单例
var globalMetricsBuffer *RingBuffer

// InitMetrics 初始化全局监控指标缓冲区
func InitMetrics() {
	// 存储最近 24 小时（按分钟聚合，共 1440 个数据点）
	globalMetricsBuffer = NewRingBuffer(1440)
}

// GetMetricsBuffer 获取全局监控指标缓冲区
func GetMetricsBuffer() *RingBuffer {
	return globalMetricsBuffer
}
