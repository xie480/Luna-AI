package infrastructure

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// HttpClient 封装 HTTP 客户端，提供便捷的 JSON 请求方法
// 做什么：用于 Qdrant REST API 调用
type HttpClient struct {
	client *http.Client
}

// QdrantAPIResponse 封装 Qdrant API 通用响应结构
type QdrantAPIResponse struct {
	Result interface{} `json:"result,omitempty"`
	Status string      `json:"status,omitempty"`
	Error  string      `json:"error,omitempty"`
}

// NewHttpClient 创建新的 HttpClient 实例
func NewHttpClient(timeout time.Duration) *HttpClient {
	return &HttpClient{
		client: &http.Client{
			Timeout: timeout,
		},
	}
}

// doRequest 执行 HTTP 请求并解析响应
func (c *HttpClient) doRequest(ctx context.Context, method, url string, body interface{}) (*QdrantAPIResponse, error) {
	var bodyReader io.Reader
	if body != nil {
		jsonBytes, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("序列化请求体失败: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBytes)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("创建 HTTP 请求失败: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("HTTP 请求失败 [method=%s url=%s]: %w", method, url, err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取响应体失败: %w", err)
	}

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("HTTP 请求返回错误 [status=%d url=%s body=%s]", resp.StatusCode, url, string(respBody))
	}

	var apiResp QdrantAPIResponse
	if err := json.Unmarshal(respBody, &apiResp); err != nil {
		// 有些端点返回非标准 JSON，返回原始响应
		return &QdrantAPIResponse{Result: string(respBody)}, nil
	}

	if apiResp.Status == "error" {
		return nil, fmt.Errorf("Qdrant API 返回错误: %s", apiResp.Error)
	}

	return &apiResp, nil
}

// Get 发送 GET 请求
func (c *HttpClient) Get(ctx context.Context, url string) (*QdrantAPIResponse, error) {
	return c.doRequest(ctx, http.MethodGet, url, nil)
}

// Put 发送 PUT 请求
func (c *HttpClient) Put(ctx context.Context, url string, body interface{}) (*QdrantAPIResponse, error) {
	return c.doRequest(ctx, http.MethodPut, url, body)
}

// Upsert 发送 PUT 请求用于 Upsert 操作
func (c *HttpClient) Upsert(ctx context.Context, url string, body interface{}) (*QdrantAPIResponse, error) {
	return c.doRequest(ctx, http.MethodPut, url, body)
}

// Search 发送 POST 请求用于搜索操作
func (c *HttpClient) Search(ctx context.Context, url string, body interface{}) (*QdrantAPIResponse, error) {
	return c.doRequest(ctx, http.MethodPost, url, body)
}

// Delete 发送 POST 请求用于删除操作
func (c *HttpClient) Delete(ctx context.Context, url string, body interface{}) (*QdrantAPIResponse, error) {
	return c.doRequest(ctx, http.MethodPost, url, body)
}

// DecodeJSON 将 API 响应的 Result 字段解码到目标对象
func (r *QdrantAPIResponse) DecodeJSON(target interface{}) error {
	if r == nil || r.Result == nil {
		return nil
	}
	jsonBytes, err := json.Marshal(r.Result)
	if err != nil {
		return fmt.Errorf("重新序列化 Result 失败: %w", err)
	}
	return json.Unmarshal(jsonBytes, target)
}
