/**
 * 统一 JSON 响应辅助
 * 做什么：提供标准化的 JSON 响应格式和写入函数，避免每个 handler 重复定义。
 * 为什么这样做：前端 ResponseModel 期望格式为 { code, msg, data, trace_id }。
 * 输入输出：无。
 * 边界条件：trace_id 暂为空字符串，后续可通过中间件注入。
 * 异常行为：无。
 */
package api

import (
	"encoding/json"
	"net/http"
)

// response 标准 JSON 响应结构，对齐前端 ResponseModel 接口
type response struct {
	Code    int         `json:"code"`
	Msg     string      `json:"msg"`
	Data    interface{} `json:"data,omitempty"`
	TraceID string      `json:"trace_id,omitempty"`
}

// writeJSON 将响应以 JSON 格式写入 http.ResponseWriter
// 自动设置 Content-Type 为 application/json
func writeJSON(w http.ResponseWriter, statusCode int, resp response) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	json.NewEncoder(w).Encode(resp)
}
