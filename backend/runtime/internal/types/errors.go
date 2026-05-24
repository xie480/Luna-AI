package types

// ErrorCode 定义全局统一的错误码枚举
type ErrorCode int

const (
	// CodeSuccess 成功
	CodeSuccess ErrorCode = 0

	// CodeSystemError 系统级错误 (1000-1999)
	CodeSystemError       ErrorCode = 1000
	CodeConfigLoadFailed  ErrorCode = 1001
	CodeDBConnectFailed   ErrorCode = 1002

	// CodeBusinessError 业务逻辑错误 (2000-2999)
	CodeBusinessError     ErrorCode = 2000
	CodeStateInvalid      ErrorCode = 2001
	CodePermissionDenied  ErrorCode = 2002

	// CodeExternalError 外部依赖错误 (3000-3999)
	CodeExternalError     ErrorCode = 3000
	CodeLLMCallFailed     ErrorCode = 3001
	CodeToolExecuteFailed ErrorCode = 3002
)

// Response 标准 JSON 响应结构
type Response struct {
	Code    ErrorCode   `json:"code"`
	Msg     string      `json:"msg"`
	Data    interface{} `json:"data"`
	TraceID string      `json:"trace_id"`
}

// NewSuccessResponse 创建成功响应
func NewSuccessResponse(data interface{}, traceID string) *Response {
	return &Response{
		Code:    CodeSuccess,
		Msg:     "success",
		Data:    data,
		TraceID: traceID,
	}
}

// NewErrorResponse 创建错误响应
func NewErrorResponse(code ErrorCode, msg string, traceID string) *Response {
	return &Response{
		Code:    code,
		Msg:     msg,
		Data:    nil,
		TraceID: traceID,
	}
}
