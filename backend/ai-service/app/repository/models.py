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

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


class MemoryStatus(str, Enum):
    """长期记忆状态枚举"""
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


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
