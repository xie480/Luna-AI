"""
Luna RAG 类型定义模块

做什么：集中定义 Phase 7 知识库检索增强所需的 Pydantic 契约、运行时状态、检索证据与事件载荷。
为什么这样做：接口契约优先于实现，所有跨层通信都携带 schema_version，避免临时联调破坏协议。
输入输出：供 API、摄入服务、切片器、检索 DAG 与仓库层复用。
边界条件：所有 ID 均使用 Snowflake 字符串，禁止 UUID；所有文本字段做长度和空值校验。
异常行为：Pydantic 校验失败会在 API 层转化为明确的 422/400 响应。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.types.constants import (
    RAG_SCHEMA_VERSION,
    RagChunkStrategy,
    RagDocumentStatus,
    RagRetrievalRoute,
    RagSourceType,
)


class RagDocumentUpdateRequest(BaseModel):
    """知识库文档更新请求"""
    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    strategy: RagChunkStrategy = Field(default=RagChunkStrategy.STRUCTURED_AST)
    chunk_size: int = Field(default=500, ge=80, le=2000)
    overlap: int = Field(default=50, ge=0, le=500)
    regex_pattern: str | None = Field(default=None, max_length=500)


class ChunkUnit(BaseModel):
    """
    RAG 标准切片单元。

    做什么：承载切片文本、层级关系、Token 估算与结构化元数据。
    为什么这样做：Qdrant 仅保存 chunk_id/doc_id 映射，完整文本由 PostgreSQL 保管，保证计算面与存储面解耦。
    输入输出：输入为切片器生成的原始文本，输出为仓库层可落盘的数据契约。
    边界条件：text 不能为空，chunk_id/document_id 必须由 Snowflake 生成。
    异常行为：字段非法时由 Pydantic 抛出 ValidationError。
    """

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    chunk_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    parent_id: str | None = Field(default=None, max_length=64)
    text: str = Field(min_length=1)
    estimated_tokens: int = Field(ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_hash: str = Field(default="", max_length=64)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验切片正文，防止空白污点数据进入 Embedding 与数据库。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("切片正文不能为空")
        return cleaned


class ChunkPreviewRequest(BaseModel):
    """
    切片策略预览请求。

    做什么：约束前端传入的沙盒预览参数。
    为什么这样做：正则切片存在计算炸弹风险，必须限制文本长度、策略枚举与超时时间。
    """

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    text: str = Field(min_length=1, max_length=200_000)
    strategy: RagChunkStrategy = Field(default=RagChunkStrategy.SLIDING_WINDOW)
    chunk_size: int = Field(default=500, ge=80, le=2000)
    overlap: int = Field(default=50, ge=0, le=500)
    regex_pattern: str | None = Field(default=None, max_length=500)
    max_fallback_tokens: int = Field(default=1200, ge=200, le=3000)
    timeout_seconds: float = Field(default=3.0, ge=0.5, le=10.0)


class ChunkPreviewResponse(BaseModel):
    """切片策略预览响应，最多返回前 5 个切片以避免前端渲染过载。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    chunks: list[ChunkUnit]
    total_chunks: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class RagDocumentDTO(BaseModel):
    """知识库文档对外展示结构。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    id: str
    filename: str
    source_type: RagSourceType
    status: RagDocumentStatus
    estimated_tokens: int
    file_hash: str | None = None
    file_size: int | None = None
    previous_version_id: str | None = None
    error_log: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RagIngestionTaskDTO(BaseModel):
    """异步摄入提交响应结构。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    task_id: str
    document_id: str


class RagUrlIngestionRequest(BaseModel):
    """URL 知识摄入请求结构。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    url: str = Field(min_length=8, max_length=2048)
    strategy: RagChunkStrategy = Field(default=RagChunkStrategy.STRUCTURED_AST)
    chunk_size: int = Field(default=500, ge=80, le=2000)
    overlap: int = Field(default=50, ge=0, le=500)
    regex_pattern: str | None = Field(default=None, max_length=500)


class RagSearchRequest(BaseModel):
    """知识库检索请求结构。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    query: str = Field(min_length=1, max_length=5000)
    disambiguated_text: str | None = None
    search_queries: list[str] | None = None
    entity_mentions: list[str] | None = None
    temporal_focus: dict[str, Any] | None = None
    route: RagRetrievalRoute | None = None
    alpha: float = Field(default=0.55, ge=0.0, le=1.0)
    retrieval_top_k: int = Field(default=20, ge=1, le=50)
    rerank_top_k: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=2, ge=0, le=5)


class RagEvidence(BaseModel):
    """
    注入 Prompt 的证据结构。

    做什么：描述检索命中的切片、父级扩展内容、得分与引用信息。
    为什么这样做：答案生成必须能引用来源，低相关证据不会污染最终上下文。
    """

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    citation_id: int = Field(ge=1)
    document_id: str
    document_name: str
    chunk_id: str
    parent_id: str | None = None
    content: str
    score: float = Field(ge=0.0)
    source_type: RagSourceType
    metadata: dict[str, Any] = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    """知识库检索响应结构。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    route: RagRetrievalRoute
    evidences: list[RagEvidence]
    prompt_context: str
    citations: list[dict[str, Any]]


class RagThoughtEventPayload(BaseModel):
    """RAG 思考链 SSE 事件载荷。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    stage: str
    msg: str


class RagCitationEventPayload(BaseModel):
    """RAG 溯源 SSE 事件载荷。"""

    schema_version: str = Field(default=RAG_SCHEMA_VERSION)
    citations: list[dict[str, Any]]
