"""
Luna AI 数据库模型定义

做什么：定义 SQLAlchemy ORM 模型，映射 PostgreSQL 数据库表结构。
为什么这样做：作为数据访问层的基础，确保与 Go 版本的 GORM 模型完全一致。
输入输出：
    - Base: SQLAlchemy 声明式基类
    - InteractionModel: 问答聚合模型
    - PromptTemplate: 提示词模板元数据模型
    - PromptVersion: 提示词模板具体版本内容模型
    - LongTermMemory: 长期记忆模型
    - ApiConfigPreset: API 配置预设模型
边界条件：
    - 字段名、类型、索引必须与现有数据库完全一致
    - 使用 Mapped 和 mapped_column 进行类型注解
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类。

    做什么：作为所有 ORM 模型的统一元数据注册入口。
    为什么这样做：FastAPI lifespan 使用 Base.metadata.create_all 自动创建缺失表结构。
    输入输出：无业务输入输出，供 SQLAlchemy 继承使用。
    边界条件：不包含业务字段，具体表结构由子类声明。
    异常行为：子类字段定义非法时由 SQLAlchemy 在映射阶段抛出异常。
    """


class MemoryStatus(str, Enum):
    """长期记忆状态枚举"""
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class HealthStatus(str, Enum):
    """MCP 健康状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


class AuthType(str, Enum):
    """MCP 鉴权类型枚举"""
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"


class InteractionModel(Base):
    """
    对应 PostgreSQL 中的 interactions 表（问答聚合）
    将用户的一问与系统的一答严格绑定为一个完整的存储单元
    """
    __tablename__ = "interactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True) # index:idx_interactions_session_id_created_at
    message_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_content: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_content: Mapped[str] = mapped_column(Text, nullable=False)
    # Thought 字段存储助手消息的内心独白（thought），用于记忆系统展示历史心理状态
    thought: Mapped[str] = mapped_column(Text, nullable=False, default="")
    emotion: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True # index:idx_interactions_session_id_created_at
    )


class PromptTemplate(Base):
    """对应 PostgreSQL 中的 prompt_templates 表（提示词模板元数据）"""
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True) # index:idx_prompt_templates_category_slot
    slot_position: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # index:idx_prompt_templates_category_slot
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_version_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PromptVersion(Base):
    """对应 PostgreSQL 中的 prompt_versions 表（提示词模板具体版本内容）"""
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list | dict] = mapped_column(JSONB, nullable=False, server_default='[]') # JSON array of strings
    status: Mapped[str] = mapped_column(String(50), nullable=False) # draft, published, archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LongTermMemory(Base):
    """
    对应 PostgreSQL 中的 long_term_memories 表（长期记忆）
    做什么：存储每日会话的深度压缩摘要，作为长期记忆的 Single Source of Truth
    """
    __tablename__ = "long_term_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True) # index:idx_ltm_session_id
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=MemoryStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ErrorLog(Base):
    """
    对应 PostgreSQL 中的 error_logs 表（前端错误日志持久化）
    做什么：记录前端捕获并上报的错误信息，包括运行时异常、Promise 拒绝、WS 通信异常等。
    为什么这样做：所有前端异常必须同时持久化到数据库，实现可追溯的错误审计。
    输入输出：
        - id: Snowflake ID
        - level: 错误级别 ERROR / WARN / CRITICAL
        - source: 错误来源（react_renderer / websocket / promise / etc）
        - message: 错误摘要
        - detail: 详细错误信息（stack trace / payload）
        - trace_id: 关联的全链路追踪 ID
        - user_agent: 用户代理信息
        - created_at: 记录时间
    """
    __tablename__ = "error_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # ERROR / WARN / CRITICAL
    source: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ApiConfigPreset(Base):
    """对应 PostgreSQL 中的 api_config_presets 表（API 配置预设）"""
    __tablename__ = "api_config_presets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    large_model_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    medium_model_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    small_model_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagDocument(Base):
    """
    对应 PostgreSQL 中的 rag_documents 表（知识库文档注册与状态追踪）

    做什么：记录知识来源、摄入状态、Token 规模和失败原因。
    为什么这样做：RAG 摄入是异步任务，前端需要轮询文档状态，后端也需要失败可恢复记录。
    输入输出：id 使用 Snowflake 字符串；source_type/status 使用统一枚举值。
    边界条件：source_type 仅允许 local_file/url，status 仅允许 parsing/embedding/completed/failed。
    异常行为：数据库约束失败时由仓库层向上抛出并写入失败状态。
    """

    __tablename__ = "rag_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RagChunk(Base):
    """
    对应 PostgreSQL 中的 rag_chunks 表（知识切片正文主表）

    做什么：保存完整切片正文、父子关系与结构化元数据。
    为什么这样做：Qdrant Payload 禁止存大段正文，检索命中后必须回表获取可信文本。
    输入输出：chunk_id 使用 Snowflake 字符串，doc_id 外键级联删除。
    边界条件：content_text 不允许为空；meta_payload 存放标题链路、来源 URL 等结构信息。
    异常行为：父块不存在不阻断普通切片，但检索扩展时只对可查父块放大上下文。
    """

    __tablename__ = "rag_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    meta_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UserProfileItem(Base):
    """
    对应 PostgreSQL 中的 user_profile_items 表（用户画像主表）。

    做什么：保存用户画像的当前事实、类别、来源、置信度、状态与冲突链。
    为什么这样做：用户画像不进入 RAG，必须作为结构化关系域事实由 PostgreSQL 统一管理。
    输入输出：id 使用雪花字符串；metadata_payload 映射数据库列 metadata。
    边界条件：category=custom 时 custom_category_name 必须存在；confidence 必须在 0 到 1。
    异常行为：违反约束时由数据库或 Pydantic Schema 在写入前拦截。
    """

    __tablename__ = "user_profile_items"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="chk_user_profile_confidence"),
        CheckConstraint("category <> 'custom' OR custom_category_name IS NOT NULL", name="chk_user_profile_custom_category"),
        Index("idx_user_profile_user_category_status", "user_id", "category", "status"),
        Index("idx_user_profile_user_updated", "user_id", "updated_at"),
        Index("idx_user_profile_normalized", "user_id", "category", "normalized_content"),
        Index("idx_user_profile_conflict_group", "user_id", "conflict_group_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local_default_user")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    custom_category_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.8)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conflict_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_payload: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserProfileItemVersion(Base):
    """
    对应 PostgreSQL 中的 user_profile_item_versions 表（用户画像版本表）。

    做什么：保存每次手动编辑、删除、模型确认、冲突覆盖前后的快照。
    为什么这样做：用户画像不能静默覆盖，所有变更必须可审计和可回溯。
    边界条件：snapshot 必须包含当时条目的关键字段；version_num 按 profile_item_id 递增。
    异常行为：版本写入失败时外层画像事务整体回滚。
    """

    __tablename__ = "user_profile_item_versions"
    __table_args__ = (Index("idx_user_profile_versions_item", "profile_item_id", "version_num"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local_default_user")
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    operator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MCPToolRegistration(Base):
    """
    对应 PostgreSQL 中的 mcp_tool_registrations 表（MCP 工具注册持久化）。

    做什么：将 MCP 工具的元数据持久化到 PostgreSQL，支持工具注册的版本管理、
            启用/禁用状态控制和跨进程共享。MCPToolRegistry 在初始化时从此表加载
            所有已注册工具，并实时同步注册状态。
    为什么这样做：Phase 12 设计要求工具注册必须落库 PG，确保进程重启后注册信息不丢失，
                并支持运行时动态注册和热加载。
    边界条件：
        - name 唯一索引，禁止重复注册。
        - enabled=False 的工具不会被混合检索召回和执行。
        - parameters_schema 以 JSONB 存储，必须符合 JSON Schema 规范。
    """
    __tablename__ = "mcp_tool_registrations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="L0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    use_case_examples: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    core_purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    final_deliverable: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    remote_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MCPMarketplace(Base):
    """
    对应 PostgreSQL 中的 mcp_marketplace 表（MCP 市场收录的 Server 主表）。
    """
    __tablename__ = "mcp_marketplace"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    repository_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    homepage_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    license: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="uncategorized", index=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    logo_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="community")
    original_data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    trust_score: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.00, index=True)
    github_stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    security_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    install_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MCPRemoteInstance(Base):
    """
    对应 PostgreSQL 中的 mcp_remote_instances 表（用户已接入的远程 MCP 实例）。
    """
    __tablename__ = "mcp_remote_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    marketplace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local_default_user", index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    auth_config_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auth_config_salt: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    proxy_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MCPMarketplaceDiscoveryLog(Base):
    """
    对应 PostgreSQL 中的 mcp_marketplace_discovery_log 表（数据采集审计日志）。
    """
    __tablename__ = "mcp_marketplace_discovery_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UserProfileConflict(Base):
    """
    对应 PostgreSQL 中的 user_profile_conflicts 表（用户画像冲突表）。

    做什么：显式记录旧画像与新画像之间的冲突关系、处理策略和原因。
    为什么这样做：冲突处理必须保留痕迹，Redis 注入只体现当前 active 版本。
    边界条件：old_item_id 和 new_item_id 必须来自同一 user_id。
    异常行为：冲突记录失败时外层 supersede 事务整体回滚。
    """

    __tablename__ = "user_profile_conflicts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local_default_user")
    old_item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    new_item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
