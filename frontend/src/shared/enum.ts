/**
 * 全局统一的错误码枚举
 * 做什么：定义前后端统一的错误码常量。
 * 为什么这样做：避免代码中出现魔法数字，统一错误处理逻辑。
 * 输入输出：无。
 * 边界条件：无。
 * 异常行为：无。
 */
export enum ErrorCode {
  SUCCESS = 0,

  // 系统级错误 (1000-1999)
  SYSTEM_ERROR = 1000,
  CONFIG_LOAD_FAILED = 1001,
  DB_CONNECT_FAILED = 1002,

  // 业务逻辑错误 (2000-2999)
  BUSINESS_ERROR = 2000,
  STATE_INVALID = 2001,
  PERMISSION_DENIED = 2002,

  // 外部依赖错误 (3000-3999)
  EXTERNAL_ERROR = 3000,
  LLM_CALL_FAILED = 3001,
  TOOL_EXECUTE_FAILED = 3002,
}

/**
 * 标准 JSON 响应结构
 * 做什么：定义前后端统一的 API 响应数据结构。
 * 为什么这样做：规范化接口返回格式，方便前端统一拦截和处理。
 * 输入输出：泛型 T 代表 data 字段的具体类型。
 * 边界条件：无。
 * 异常行为：无。
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface ResponseModel<T = any> {
  code: ErrorCode;
  msg: string;
  data: T;
  trace_id: string;
}
