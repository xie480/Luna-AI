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


class ToolConfigStatus(str, Enum):
    """工具配置状态枚举。"""
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


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
    # --- Phase 12 新增：关联技能 ID。当工具属于某个 Skill 时非空；独立工具时为空。 ---
    skill_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
        comment="关联的技能 ID。当工具属于某个 Skill 时非空；独立工具时为空。",
    )
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


class Skill(Base):
    """
    对应 PostgreSQL 中的 skills 表（技能主表）。

    做什么：存储技能的元数据定义。Skill 是 MCP 能力的顶层抽象，
            一个 Skill 包含一组 Tool、Resource 和 Prompt，
            系统通过三阶段 Agent 流水线执行 Skill。
    为什么这样做：将工具、资源、提示词统一组织为 Skill，
                实现"能力指针"的抽象层。Agent 1 在初筛阶段
                仅操作 Skill 级别的元数据，不展开具体工具。
    输入输出：
        - id: 雪花算法生成的唯一标识。
        - name: 技能唯一名称。
        - description: 技能功能描述。
        - metadata: JSONB 存储的元数据。
        - version: 技能版本号。
        - enabled: 是否启用。
    边界条件：
        - name 唯一索引，禁止重复创建。
        - enabled=False 的技能不会被 Agent 1 召回。
        - metadata 支持存储版本信息、作者信息等扩展字段。
    """
    __tablename__ = "skills"
    __table_args__ = (
        Index("idx_skills_enabled", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Prompt(Base):
    """
    对应 PostgreSQL 中的 prompts 表（提示模板表，关联 skill/tool）。

    做什么：存储与 Skill 或 Tool 关联的提示模板内容。每个 Skill 可以定义
            多个阶段的 Prompt（screening/loading/execution），
            我们去除了三槽位设计，直接保存单一内容 (content)。
    为什么这样做：将 Prompt 管理与 Skill/Tool 绑定，而不是分散在
                业务代码中。支持版本管理和阶段化注入。
    输入输出：
        - id: 雪花算法生成的唯一标识。
        - skill_id: 关联的技能 ID。
        - tool_id: 关联的工具 ID（用于给 tool 单独挂载 prompt）。
        - phase: 阶段标识（screening/loading/execution）。
        - content: 完整的模板内容。
        - variables: 模板变量定义。
        - version_num: 版本号，支持版本回溯。
        - status: draft/published/archived。
    边界条件：
        - (skill_id 或 tool_id) + phase + version_num 联合唯一索引（应用层保证）。
        - status 默认 draft，published 状态不可直接修改。
    """
    __tablename__ = "prompts"
    __table_args__ = (
        Index("idx_prompts_skill_phase", "skill_id", "phase"),
        Index("idx_prompts_tool_phase", "tool_id", "phase"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("skills.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("mcp_tool_registrations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="阶段标识：screening（初筛）/ loading（加载）/ execution（执行）",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variables: Mapped[list | dict] = mapped_column(
        JSONB, nullable=False, server_default="[]",
        comment="模板变量定义，格式：[{name: str, description: str, required: bool}]",
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Resource(Base):
    """
    对应 PostgreSQL 中的 resources 表（资源表，关联 skill）。

    做什么：存储与 Skill 关联的可加载资源定义。资源可以是本地文件、
            API 接口、数据库查询等。执行阶段由子 Agent 按需加载。
    为什么这样做：将资源管理与 Skill 绑定，支持文件读写方式的
                资源加载，并行的子 Agent 提取关键信息。
    输入输出：
        - id: 雪花算法生成的唯一标识。
        - skill_id: 关联的技能 ID。
        - name: 资源名称。
        - resource_type: 资源类型（file/api/database）。
        - uri: 资源 URI（文件路径/API URL/查询语句）。
        - description: 资源描述。
        - mime_type: MIME 类型（text/plain, application/json 等）。
        - metadata: JSONB 存储的扩展元数据。
        - auto_load: 加载 Skill 时是否自动加载此资源。
    边界条件：
        - resource_type 仅支持 file/api/database/embedded。
        - file 类型的资源在执行阶段通过文件读写方式加载。
        - auto_load=true 的资源在 Agent 2 阶段自动注入。
    """
    __tablename__ = "resources"
    __table_args__ = (
        Index("idx_resources_skill_id", "skill_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="file",
        comment="资源类型：file（本地文件）/ api（API 接口）/ database（数据库查询）/ embedded（内嵌）",
    )
    uri: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    auto_load: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MCPServerRegistration(Base):
    """
    对应 PostgreSQL 中的 mcp_server_registrations 表（本地 MCP 服务器注册）。

    做什么：存储用户在本机配置的 MCP 服务器注册信息，包括启动命令、参数、
            环境变量等完整配置。服务器与工具是独立的概念：一个服务器进程可以
            提供多个工具，此表只记录服务器本身的配置与状态。
    为什么这样做：Phase 12 要求本地 MCP 服务器的注册信息独立落库，与
                 mcp_tool_registrations（工具注册表）逻辑解耦。服务器配置
                 直接映射为表字段，不再嵌套存储在 parameters_schema JSONB 中。
    边界条件：
        - name 唯一索引，禁止重复注册。
        - enabled=False 的服务器不会被尝试启动。
        - health_status 跟踪服务器进程的健康状态（unknown/online/offline/error）。
        - metadata 存储扩展属性，如版本号、作者信息等。
    """
    __tablename__ = "mcp_server_registrations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    """服务器唯一名称。"""
    command: Mapped[str] = mapped_column(String(512), nullable=False)
    """启动命令（如 node、python 等）。"""
    args: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    """命令参数列表。"""
    env: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    """环境变量键值对。"""
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """服务器描述信息。"""
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """是否启用。"""
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """此服务器提供的工具数量。"""
    endpoint_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    """服务器暴露的 endpoint URL（适用于 SSE 模式）。"""
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    """健康状态：unknown / online / offline / error。"""
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    """扩展元数据（版本号、作者信息等）。"""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ToolConfig(Base):
    """
    对应 PostgreSQL 中的 tool_configs 表（MCP 工具独立配置表）。

    做什么：存储 MCP 工具的自定义配置参数（键值对），每个工具有一组独立的配置。
            例如 web_search 工具的 SearXNG URL 和超时设置存储在此表。
            工具在运行时通过 ToolConfigManager 读取此表中的配置。
    为什么这样做：工具配置不应与系统环境变量（.env）耦合，而是让用户通过前端
                Skill 面板中每个工具条目旁的"配置"按钮，在模态框中独立设置。
    边界条件：
        - tool_name 唯一，一个工具一条配置记录。
        - config_data 以 JSONB 存储，存储该工具的所有配置键值对。
        - status 标记配置是否启用（ACTIVE / INACTIVE）。
        - 配置变更后必须调用 ToolConfigManager.reload() 使内存缓存生效。
    """
    __tablename__ = "tool_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
        comment="工具名称。与 MCPToolRegistry 中的工具名称一一对应。",
    )
    config_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="工具配置键值对。不同工具有不同的配置字段，"
                "由工具自身的配置 Schema 定义。",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE",
        comment="配置状态：ACTIVE（启用）/ INACTIVE（禁用）。",
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="配置说明或备注。",
    )
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
