"""
Luna 用户画像 Schema 定义。

做什么：定义用户画像 API 请求响应、模型提取输出和内部变更计划结构。
为什么这样做：所有跨层通信和模型输出必须先经过 Pydantic 校验，再进入数据库事务。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.types.constants import (
    USER_PROFILE_CACHE_SCHEMA_VERSION,
    USER_PROFILE_CATEGORY_LABELS,
    USER_PROFILE_EXTRACT_SCHEMA_VERSION,
    USER_PROFILE_MUTATION_SCHEMA_VERSION,
    USER_PROFILE_SCHEMA_VERSION,
    UserProfileCacheStatus,
    UserProfileCategory,
    UserProfileSourceType,
    UserProfileStatus,
)

CONTENT_MIN_LENGTH = 4
CONTENT_MAX_LENGTH = 200
EVIDENCE_MIN_LENGTH = 4
EVIDENCE_MAX_LENGTH = 300
MAX_EXTRACTED_CANDIDATES = 20
UNCERTAIN_WORDS = ("可能", "也许", "似乎", "大概", "或许")
HIGH_RISK_FLAGS = ("hypothetical", "joke", "sarcasm", "perfunctory", "quote", "roleplay", "temporary_emotion", "fictional")


def validate_profile_content(value: str) -> str:
    """
    校验并清洗画像正文。

    做什么：统一限制画像正文长度和不确定表达。
    为什么这样做：避免把不稳定、不明确的信息写入用户画像。
    输入输出：输入原始正文，输出去首尾空格后的正文。
    边界条件：长度必须为 4 到 200 字。
    异常行为：非法时抛出 ValueError，由 API 层转为明确错误码。
    """
    content = value.strip()
    if len(content) < CONTENT_MIN_LENGTH or len(content) > CONTENT_MAX_LENGTH:
        raise ValueError("用户画像内容长度必须在 4 到 200 字之间")
    if any(word in content for word in UNCERTAIN_WORDS):
        raise ValueError("用户画像内容不能包含不确定事实表达")
    return content


class UserProfileItemDTO(BaseModel):
    """用户画像前端展示 DTO。"""

    schema_version: Literal["user_profile.v1"] = USER_PROFILE_SCHEMA_VERSION
    id: str
    category: UserProfileCategory
    category_label: str
    custom_category_name: str | None = None
    content: str
    source_type: UserProfileSourceType
    confidence: float = Field(ge=0.0, le=1.0)
    status: UserProfileStatus
    source_excerpt: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_confirmed_at: str | None = None


class UserProfileListResponse(BaseModel):
    """用户画像列表响应。"""

    schema_version: Literal["user_profile.v1"] = USER_PROFILE_SCHEMA_VERSION
    items: list[UserProfileItemDTO]
    grouped: dict[str, list[UserProfileItemDTO]]
    total: int
    cache_status: UserProfileCacheStatus


class UserProfileMutationRequest(BaseModel):
    """手动新增或编辑用户画像请求。"""

    schema_version: Literal["user_profile.v1"] = USER_PROFILE_SCHEMA_VERSION
    category: UserProfileCategory
    custom_category_name: str | None = Field(default=None, max_length=64)
    content: str
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        return validate_profile_content(value)

    @field_validator("custom_category_name")
    @classmethod
    def _normalize_custom_category_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _validate_custom_category(self) -> "UserProfileMutationRequest":
        if self.category == UserProfileCategory.CUSTOM and not self.custom_category_name:
            raise ValueError("自定义类别必须填写类别名称")
        return self


class UserProfileCacheStatusResponse(BaseModel):
    """用户画像 Redis 压缩缓存状态响应。"""

    schema_version: Literal["user_profile.cache.v1"] = USER_PROFILE_CACHE_SCHEMA_VERSION
    status: UserProfileCacheStatus
    updated_at: str | None = None
    source_item_count: int = 0
    summary_length: int = 0
    last_error: str = ""


class UserProfileExtractionTaskRequest(BaseModel):
    """手动触发用户画像提取任务请求。"""

    schema_version: Literal["user_profile.v1"] = USER_PROFILE_SCHEMA_VERSION
    session_id: str = Field(min_length=1, max_length=64)
    messages_text: str = Field(min_length=1, max_length=20000)


class ExtractedProfileCandidate(BaseModel):
    """模型提取出的用户画像候选。"""

    category: UserProfileCategory
    custom_category_name: str | None = Field(default=None, max_length=64)
    content: str
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_risk_flags: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=500)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        return validate_profile_content(value)

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, value: str) -> str:
        evidence = value.strip()
        if len(evidence) < EVIDENCE_MIN_LENGTH or len(evidence) > EVIDENCE_MAX_LENGTH:
            raise ValueError("用户画像证据片段长度必须在 4 到 300 字之间")
        return evidence

    @field_validator("source_risk_flags")
    @classmethod
    def _normalize_risk_flags(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def _validate_candidate(self) -> "ExtractedProfileCandidate":
        if self.category == UserProfileCategory.CUSTOM and not self.custom_category_name:
            raise ValueError("自定义类别候选必须填写类别名称")
        if any(flag in HIGH_RISK_FLAGS for flag in self.source_risk_flags) and self.confidence >= 0.6:
            raise ValueError("包含高风险标记的候选置信度必须低于 0.6")
        return self


class RejectedProfileCandidate(BaseModel):
    """模型拒绝入库的候选说明。"""

    raw_claim: str = Field(min_length=1, max_length=300)
    evidence: str = Field(min_length=1, max_length=300)
    reject_reason: str = Field(min_length=1, max_length=500)


class UserProfileExtractOutput(BaseModel):
    """模型提取用户画像的结构化输出。"""

    schema_version: Literal["user_profile.extract.v1"] = USER_PROFILE_EXTRACT_SCHEMA_VERSION
    session_id: str
    candidates: list[ExtractedProfileCandidate] = Field(default_factory=list, max_length=MAX_EXTRACTED_CANDIDATES)
    rejected_candidates: list[RejectedProfileCandidate] = Field(default_factory=list, max_length=MAX_EXTRACTED_CANDIDATES)


class ProfileMutation(BaseModel):
    """用户画像内部变更指令。"""

    action: Literal["add", "confirm_existing", "supersede", "reject"]
    candidate: ExtractedProfileCandidate
    target_item_id: str | None = None
    reason: str


class ProfileMutationPlan(BaseModel):
    """用户画像内部变更计划。"""

    schema_version: Literal["user_profile.mutation.v1"] = USER_PROFILE_MUTATION_SCHEMA_VERSION
    mutations: list[ProfileMutation]


class UserProfileCacheRebuildResponse(BaseModel):
    """用户画像缓存重建任务响应。"""

    schema_version: Literal["user_profile.cache.v1"] = USER_PROFILE_CACHE_SCHEMA_VERSION
    task_id: str
    status: UserProfileCacheStatus


class UserProfileExtractionTaskResponse(BaseModel):
    """用户画像提取任务响应。"""

    schema_version: Literal["user_profile.v1"] = USER_PROFILE_SCHEMA_VERSION
    task_id: str
    status: UserProfileCacheStatus


def category_label(category: str, custom_category_name: str | None = None) -> str:
    """返回用户画像类别中文名。"""
    if category == UserProfileCategory.CUSTOM.value and custom_category_name:
        return custom_category_name
    return USER_PROFILE_CATEGORY_LABELS.get(category, category)


def datetime_to_text(value: datetime | None) -> str | None:
    """将数据库时间转换为前端可读 ISO 字符串。"""
    return value.isoformat() if value else None


def safe_metadata(value: Any) -> dict[str, Any]:
    """确保 metadata 始终是字典。"""
    return value if isinstance(value, dict) else {}
