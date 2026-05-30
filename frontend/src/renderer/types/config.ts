/**
 * Luna AI 全局配置类型定义
 * 做什么：定义前端使用的安全配置数据结构。
 * 为什么这样做：确保前端不接触敏感信息（如明文 API Key），同时提供类型安全的配置访问。
 */

export interface SafeConfig {
  /** 是否已设置 LLM API Key（脱敏状态） */
  has_llm_api_key: boolean;
  /** LLM API 基础 URL */
  llm_base_url?: string;
  /** 当前使用的 LLM 模型名称 */
  llm_model?: string;
  /** LLM 最大输出 Token 数 */
  llm_max_tokens?: number;
  /** LLM 采样温度 */
  llm_temperature?: number;
  /** 允许其他动态配置项 */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}
