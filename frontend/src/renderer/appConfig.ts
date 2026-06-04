/**
 * Luna AI 前端全局配置模块
 *
 * 做什么：集中管理所有前端配置项。
 *         优先从 Vite 环境变量（import.meta.env）读取，
 *         若不存在则使用硬编码默认值兜底。
 * 为什么这样做：避免前端多个模块硬编码端口/IP，
 *             同时支持通过根目录 .env 文件统一配置。
 *
 * 配置来源：
 *   - .env 文件：根目录下的 .env 文件，通过 Vite 的 envDir 配置读取
 *   - 环境变量前缀：VITE_ 开头的变量会被 Vite 注入到 import.meta.env
 *   - 默认值兜底：当环境变量不存在时，使用下方定义的默认值
 */

/**
 * AI 服务 HTTP 端口
 * 对应根目录 .env 中的 VITE_AI_SERVICE_PORT / AI_SERVICE_PORT
 */
export const AI_SERVICE_PORT: number = (() => {
  try {
    const envPort = import.meta.env.VITE_AI_SERVICE_PORT
    if (envPort && typeof envPort === 'string') {
      const parsed = parseInt(envPort, 10)
      if (!isNaN(parsed) && parsed > 0 && parsed < 65536) {
        return parsed
      }
    }
  } catch {
    // import.meta.env 在非 Vite 环境下不可用，使用默认值
  }
  return 8088 // 默认值，与 .env 保持一致
})()

/**
 * AI 服务基础 URL
 */
export const AI_SERVICE_BASE_URL: string = `http://127.0.0.1:${AI_SERVICE_PORT}`

/**
 * SSE 通知端点
 */
export const SSE_NOTIFICATION_URL: string = `${AI_SERVICE_BASE_URL}/sse/notifications`

/**
 * Health 检查端点
 */
export const HEALTH_URL: string = `${AI_SERVICE_BASE_URL}/health`
