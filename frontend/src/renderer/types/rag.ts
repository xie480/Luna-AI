/**
 * Luna RAG 前端类型契约
 *
 * 做什么：集中描述 Phase 7 知识库管理、切片预览、摄入队列、检索思考链与溯源引用所需的数据结构。
 * 为什么这样做：前端只作为 Python 控制面的状态投影与交互控制台，所有跨层字段在这里保持强类型约束，避免组件内散落临时对象。
 * 输入输出：输入来自用户表单、上传文件与 SSE/HTTP 响应；输出传递给 ragService 与 Zustand Store。
 * 边界条件：所有 Snowflake ID 均使用 string 承载，严禁转为 number，防止 64 位整数精度丢失。
 * 异常行为：字段非法时由调用方在提交前进行显式校验，服务层仍会再次校验响应结构。
 */
import {
  RAG_CHUNK_STRATEGY,
  RAG_DOCUMENT_STATUS,
  RAG_RETRIEVAL_ROUTE,
  RAG_SCHEMA_VERSION,
  RAG_SOURCE_TYPE,
} from '../../shared/enum';

/** 后端标准 JSON 响应中成功状态的数值。 */
export const RAG_SUCCESS_CODE = 0;

/** 文件上传最大体积：50MB，超过后前端直接拦截，避免本地 IPC 与后端解析链路被大文件压垮。 */
export const RAG_MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/** 预览沙盒的硬性超时时间，配合 AbortController 防止正则灾难性回溯拖垮 UI。 */
export const RAG_PREVIEW_TIMEOUT_MS = 8000;

/** 知识文档状态轮询间隔，短于后端摄入状态流转但不会造成请求风暴。 */
export const RAG_POLL_INTERVAL_MS = 2000;

/** 知识文档状态轮询最长保留时间，超时后转入本地挂起提示，等待用户重新刷新。 */
export const RAG_POLL_TIMEOUT_MS = 10 * 60 * 1000;

/** 沙盒预览测试文本长度上限，与后端 200000 字符限制对齐。 */
export const RAG_PREVIEW_TEXT_MAX_LENGTH = 200000;

/** 切片策略枚举类型。 */
export type RagChunkStrategy = typeof RAG_CHUNK_STRATEGY[keyof typeof RAG_CHUNK_STRATEGY];

/** 知识来源类型枚举。 */
export type RagSourceType = typeof RAG_SOURCE_TYPE[keyof typeof RAG_SOURCE_TYPE];

/** 文档摄入状态枚举。 */
export type RagDocumentStatus = typeof RAG_DOCUMENT_STATUS[keyof typeof RAG_DOCUMENT_STATUS];

/** 检索路由枚举。 */
export type RagRetrievalRoute = typeof RAG_RETRIEVAL_ROUTE[keyof typeof RAG_RETRIEVAL_ROUTE];

/** 前端额外的文档展示状态，用于表示后端失联后的安全挂起态。 */
export type KnowledgeDisplayStatus = RagDocumentStatus | 'offline_suspended';

/** 滑窗切片策略参数。 */
export interface SlidingWindowParams {
  chunkSize: number;
  chunkOverlap: number;
}

/** 结构化 Markdown/文档切分参数。 */
export interface StructuredParams {
  includeMetadata: boolean;
  keepTablesIntact: boolean;
}

/** 语义父子级联切分参数。 */
export interface SemanticParams {
  delimiters: string[];
  enableParentChild: boolean;
}

/** 正则切分参数。 */
export interface RegexParams {
  startRegex: string;
  endRegex: string;
  maxTokenFallback: number;
}

/** 切片策略表单通用 Props。 */
export interface StrategyFormProps<T> {
  defaultValues: T;
  onChange: (newParams: T) => void;
  disabled?: boolean;
}

/** 后端切片策略通用载荷。 */
export interface RagChunkRequestPayload {
  schema_version: typeof RAG_SCHEMA_VERSION;
  strategy: RagChunkStrategy;
  chunk_size: number;
  overlap: number;
  regex_pattern?: string;
  max_fallback_tokens?: number;
}

/** 切片预览请求。 */
export interface ChunkPreviewPayload extends RagChunkRequestPayload {
  text: string;
  timeout_seconds: number;
}

/** 后端返回的单个 Chunk 单元。 */
export interface ChunkPreviewUnit {
  schema_version: string;
  chunk_id: string;
  document_id: string;
  parent_id: string | null;
  text: string;
  estimated_tokens: number;
  metadata: Record<string, unknown>;
}

/** 切片预览响应。 */
export interface ChunkPreviewResponse {
  schema_version: string;
  chunks: ChunkPreviewUnit[];
  total_chunks: number;
  warnings: string[];
}

/** 后端知识库文档 DTO。 */
export interface KnowledgeDocument {
  schema_version: string;
  id: string;
  filename: string;
  source_type: RagSourceType;
  status: RagDocumentStatus;
  estimated_tokens: number;
  error_log: string | null;
  description: string;
  created_at: string | null;
}

/** 前端知识库文档展示模型。 */
export interface KnowledgeDocumentView extends KnowledgeDocument {
  display_status: KnowledgeDisplayStatus;
}

/** 摄入任务提交响应。 */
export interface RagIngestionTaskResponse {
  schema_version: string;
  task_id: string;
  document_id: string;
}

/** 文档更新任务提交响应。 */
export interface RagDocumentUpdateResponse {
  schema_version: string;
  task_id: string;
  document_id: string;
  previous_version_id: string;
}
/** URL 摄入请求。 */
export interface RagUrlIngestionPayload extends RagChunkRequestPayload {
  url: string;
  description?: string;
}

/** 检索证据项，用于溯源弹窗。 */
export interface RagEvidence {
  schema_version: string;
  citation_id: number;
  document_id: string;
  document_name: string;
  chunk_id: string;
  parent_id: string | null;
  content: string;
  score: number;
  source_type: RagSourceType;
  metadata: Record<string, unknown>;
}

/** 检索响应。 */
export interface RagSearchResponse {
  schema_version: string;
  route: RagRetrievalRoute;
  evidences: RagEvidence[];
  prompt_context: string;
  citations: Array<Record<string, unknown>>;
}

/** RAG 思考链事件。 */
export interface RagThoughtEvent {
  schema_version: string;
  stage: 'router' | 'searching' | 'evaluating' | 'rewriting' | 'generating';
  description: string;
  timestamp: number;
}

/** 后端可能下发的原始思考链事件载荷。 */
export interface RawRagThoughtPayload {
  schema_version?: string;
  stage?: string;
  description?: string;
  msg?: string;
  timestamp?: number;
}

/** RAG 引用事件载荷。 */
export interface RagCitationEventPayload {
  schema_version: string;
  citations: RagEvidence[];
}

/** 标准 API 响应。 */
export interface RagApiResponse<T> {
  code: number;
  msg: string;
  data: T | null;
  trace_id: string;
}

/** 文档过滤条件。 */
export interface KnowledgeFilterState {
  keyword: string;
  sourceType: 'all' | RagSourceType;
  status: 'all' | KnowledgeDisplayStatus;
}

/** 知识摄入进度快照。 */
export interface IngestionProgressSnapshot {
  activeCount: number;
  completedCount: number;
  failedCount: number;
  globalPercent: number;
}
