/**
 * Luna RAG 服务层
 *
 * 做什么：封装 Phase 7 知识库相关 HTTP API，包括切片预览、文件摄入、URL 摄入、文档查询、删除与检索。
 * 为什么这样做：React 组件不得直接拼装网络协议，所有跨层通信都统一经过服务层，便于错误处理、TraceID 注入和 AbortController 生命周期管理。
 * 输入输出：输入为强类型请求载荷，输出为经过 ResponseModel 校验后的业务数据。
 * 边界条件：预览请求会取消上一轮未完成请求；上传文件会在调用方完成大小校验后以 FormData 提交。
 * 异常行为：HTTP 非 2xx、业务 code 非 0、响应结构缺失 data 均抛出中文错误，调用方负责展示降级状态。
 */
import { AI_SERVICE_BASE_URL } from '../appConfig';
import { useSystemStore } from '../stores/systemStore';
import { generateId } from '../../shared/utils/snowflake';
import {
  ChunkPreviewPayload,
  ChunkPreviewResponse,
  KnowledgeDocument,
  RagApiResponse,
  RagChunkRequestPayload,
  RagDocumentUpdateResponse,
  RagIngestionTaskResponse,
  RagSearchResponse,
  RagUrlIngestionPayload,
  RAG_PREVIEW_TIMEOUT_MS,
  RAG_SUCCESS_CODE,
} from '../types/rag';

/** RAG API 根路径。 */
const RAG_API_BASE_URL = `${AI_SERVICE_BASE_URL}/api/v1/rag`;

/** 用户主动触发新预览时的中止原因。 */
const PREVIEW_ABORT_REASON_NEW_REQUEST = 'USER_TRIGGERED_NEW_REQUEST';

/** 预览超时时的中止原因。 */
const PREVIEW_ABORT_REASON_TIMEOUT = 'TIMEOUT';

/** 生成请求 TraceID，优先复用当前链路 TraceID。 */
function getTraceId(): string {
  return useSystemStore.getState().currentTraceID || `web-${generateId()}`;
}

/** 判断未知值是否为标准 API 响应结构。 */
function isRagApiResponse<T>(value: unknown): value is RagApiResponse<T> {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === 'number' && typeof candidate.msg === 'string' && typeof candidate.trace_id === 'string';
}

/** 从 fetch 响应中解析标准 ResponseModel，并提取 data。 */
async function parseRagResponse<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    throw new Error(`解析 RAG 响应失败：${String(error)}`);
  }

  if (!response.ok) {
    if (isRagApiResponse<T>(body)) {
      throw new Error(body.msg || `RAG 请求失败：HTTP ${response.status}`);
    }
    throw new Error(`RAG 请求失败：HTTP ${response.status}`);
  }

  if (!isRagApiResponse<T>(body)) {
    throw new Error('RAG 响应结构不符合统一 ResponseModel 契约');
  }

  if (body.code !== RAG_SUCCESS_CODE) {
    throw new Error(body.msg || 'RAG 请求返回业务错误');
  }

  if (body.data === null || body.data === undefined) {
    throw new Error('RAG 响应缺少业务数据');
  }

  return body.data;
}

/** 通过 QueryString 拼接安全的 GET URL。 */
function buildUrl(path: string, params?: Record<string, string | number>): string {
  const url = new URL(`${RAG_API_BASE_URL}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * RAG 服务类。
 * 该类维护预览 AbortController 生命周期：每次新预览都会取消旧预览，并在 finally 中释放定时器。
 */
class RagService {
  private previewAbortController: AbortController | null = null;

  /** 获取切片预览，包含硬性超时和上一请求取消逻辑。 */
  async getChunkPreview(payload: ChunkPreviewPayload): Promise<ChunkPreviewResponse> {
    if (this.previewAbortController) {
      this.previewAbortController.abort(PREVIEW_ABORT_REASON_NEW_REQUEST);
    }

    const controller = new AbortController();
    this.previewAbortController = controller;
    const timeoutId = window.setTimeout(() => {
      controller.abort(PREVIEW_ABORT_REASON_TIMEOUT);
    }, RAG_PREVIEW_TIMEOUT_MS);

    try {
      const response = await fetch(`${RAG_API_BASE_URL}/chunk/preview`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-ID': getTraceId(),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      return await parseRagResponse<ChunkPreviewResponse>(response);
    } catch (error) {
      if (controller.signal.aborted) {
        const reason = String(controller.signal.reason || '');
        if (reason === PREVIEW_ABORT_REASON_TIMEOUT) {
          throw new Error('切片预览超时，请优化切分规则或缩短测试文本');
        }
        throw new Error('已取消上一轮切片预览请求');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      if (this.previewAbortController === controller) {
        this.previewAbortController = null;
      }
    }
  }

  /** 获取切片预览 (本地文件)，先提取文本再切片返回。 */
  async getChunkPreviewFromFile(file: File, config: RagChunkRequestPayload): Promise<ChunkPreviewResponse> {
    if (this.previewAbortController) {
      this.previewAbortController.abort(PREVIEW_ABORT_REASON_NEW_REQUEST);
    }

    const controller = new AbortController();
    this.previewAbortController = controller;
    const timeoutId = window.setTimeout(() => {
      controller.abort(PREVIEW_ABORT_REASON_TIMEOUT);
    }, RAG_PREVIEW_TIMEOUT_MS);

    try {
      const formData = new FormData();
      formData.set('file', file);
      formData.set('strategy', config.strategy);
      formData.set('chunk_size', String(config.chunk_size));
      formData.set('overlap', String(config.overlap));
      if (config.regex_pattern) {
        formData.set('regex_pattern', config.regex_pattern);
      }

      const response = await fetch(`${RAG_API_BASE_URL}/chunk/preview/file`, {
        method: 'POST',
        headers: {
          'X-Trace-ID': getTraceId(),
        },
        body: formData,
        signal: controller.signal,
      });
      return await parseRagResponse<ChunkPreviewResponse>(response);
    } catch (error) {
      if (controller.signal.aborted) {
        const reason = String(controller.signal.reason || '');
        if (reason === PREVIEW_ABORT_REASON_TIMEOUT) {
          throw new Error('文件解析预览超时，可能文件过大或策略计算复杂度过高');
        }
        throw new Error('已取消上一轮文件切片预览请求');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      if (this.previewAbortController === controller) {
        this.previewAbortController = null;
      }
    }
  }

  /** 获取切片预览 (URL)，前后端连通后抓取文本并切片返回。 */
  async getChunkPreviewFromUrl(payload: RagUrlIngestionPayload): Promise<ChunkPreviewResponse> {
    if (this.previewAbortController) {
      this.previewAbortController.abort(PREVIEW_ABORT_REASON_NEW_REQUEST);
    }

    const controller = new AbortController();
    this.previewAbortController = controller;
    const timeoutId = window.setTimeout(() => {
      controller.abort(PREVIEW_ABORT_REASON_TIMEOUT);
    }, RAG_PREVIEW_TIMEOUT_MS);

    try {
      const response = await fetch(`${RAG_API_BASE_URL}/chunk/preview/url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Trace-ID': getTraceId(),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      return await parseRagResponse<ChunkPreviewResponse>(response);
    } catch (error) {
      if (controller.signal.aborted) {
        const reason = String(controller.signal.reason || '');
        if (reason === PREVIEW_ABORT_REASON_TIMEOUT) {
          throw new Error('网址抓取预览超时，可能是目标网站响应缓慢');
        }
        throw new Error('已取消上一轮网址切片预览请求');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      if (this.previewAbortController === controller) {
        this.previewAbortController = null;
      }
    }
  }

  /** 提交本地文件摄入任务，后端立即返回 task_id 与 document_id。 */
  async submitLocalFile(file: File, config: RagChunkRequestPayload, description = ''): Promise<RagIngestionTaskResponse> {
    const formData = new FormData();
    formData.set('file', file);
    formData.set('strategy', config.strategy);
    formData.set('chunk_size', String(config.chunk_size));
    formData.set('overlap', String(config.overlap));
    if (config.regex_pattern) {
      formData.set('regex_pattern', config.regex_pattern);
    }
    if (description) {
      formData.set('description', description);
    }

    const response = await fetch(`${RAG_API_BASE_URL}/knowledge/upload`, {
      method: 'POST',
      headers: {
        'X-Trace-ID': getTraceId(),
      },
      body: formData,
    });
    return await parseRagResponse<RagIngestionTaskResponse>(response);
  }

  /** 提交 URL 摄入任务。 */
  async submitUrl(payload: RagUrlIngestionPayload): Promise<RagIngestionTaskResponse> {
    const response = await fetch(`${RAG_API_BASE_URL}/knowledge/url`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': getTraceId(),
      },
      body: JSON.stringify(payload),
    });
    return await parseRagResponse<RagIngestionTaskResponse>(response);
  }

  /** 拉取知识库文档列表。 */
  async listKnowledge(limit = 100): Promise<KnowledgeDocument[]> {
    const response = await fetch(buildUrl('/knowledge', { limit }), {
      method: 'GET',
      headers: {
        'X-Trace-ID': getTraceId(),
      },
    });
    return await parseRagResponse<KnowledgeDocument[]>(response);
  }

  /** 查询单个知识库文档状态。 */
  async getKnowledgeDocument(documentId: string): Promise<KnowledgeDocument> {
    if (!documentId.trim()) {
      throw new Error('知识库文档 ID 不能为空');
    }
    const response = await fetch(buildUrl(`/knowledge/${encodeURIComponent(documentId)}`), {
      method: 'GET',
      headers: {
        'X-Trace-ID': getTraceId(),
      },
    });
    return await parseRagResponse<KnowledgeDocument>(response);
  }

  /**
   * 提交文档更新任务。
   *
   * 做什么：基于 Blue-Purple Update 策略，上传新文件替换已存在文档的内容。
   * 旧文档保持 ACTIVE 不受影响，新版本在后台完成切片与向量化后通过原子状态翻转上线。
   * 为什么这样做：避免"先删后插"导致检索真空期，保证更新期间知识库查询不中断。
   * 输入输出：输入为原文档 ID + 新文件 FormData，输出为更新任务响应（含新 document_id 和版本关联信息）。
   * 边界条件：原文档必须处于 ACTIVE 状态；新文件格式与大小限制同上传一致。
   * 异常行为：若原文档不存在或处于处理中状态，后端返回业务错误。
   */
  async updateKnowledge(documentId: string, file: File, config: RagChunkRequestPayload): Promise<RagDocumentUpdateResponse> {
    const formData = new FormData();
    formData.set('file', file);
    formData.set('strategy', config.strategy);
    formData.set('chunk_size', String(config.chunk_size));
    formData.set('overlap', String(config.overlap));
    if (config.regex_pattern) {
      formData.set('regex_pattern', config.regex_pattern);
    }

    const response = await fetch(
      buildUrl(`/knowledge/${encodeURIComponent(documentId)}/update`),
      {
        method: 'PUT',
        headers: {
          'X-Trace-ID': getTraceId(),
        },
        body: formData,
      }
    );
    return await parseRagResponse<RagDocumentUpdateResponse>(response);
  }

  /** 删除文档及其关联知识切片。当前后端未暴露删除接口时会返回明确错误而非假成功。 */
  async deleteKnowledge(documentId: string): Promise<void> {
    if (!documentId.trim()) {
      throw new Error('知识库文档 ID 不能为空');
    }
    const response = await fetch(buildUrl(`/knowledge/${encodeURIComponent(documentId)}`), {
      method: 'DELETE',
      headers: {
        'X-Trace-ID': getTraceId(),
      },
    });
    await parseRagResponse<unknown>(response);
  }

  /** 执行知识库检索，供溯源组件按需获取上下文证据。 */
  async searchKnowledge(query: string): Promise<RagSearchResponse> {
    if (!query.trim()) {
      throw new Error('检索问题不能为空');
    }
    const response = await fetch(`${RAG_API_BASE_URL}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Trace-ID': getTraceId(),
      },
      body: JSON.stringify({
        schema_version: 'rag.v1',
        query: query.trim(),
      }),
    });
    return await parseRagResponse<RagSearchResponse>(response);
  }
}

export const ragService = new RagService();
