"""
用户画像模块单元测试。

做什么：验证 UserProfile 模块的 Schema、冲突处理器、常量枚举和缓存模块。
为什么这样做：确保画像提取、重复检测、冲突处理、校验逻辑按文档实现。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.types.constants import (
    USER_PROFILE_DEFAULT_USER_ID,
    UserProfileCacheStatus,
    UserProfileCategory,
    UserProfileSourceType,
    UserProfileStatus,
)
from app.user_profile.cache import UserProfileCache
from app.user_profile.conflict_resolver import UserProfileConflictResolver, normalize_profile_content
from app.user_profile.schemas import (
    ExtractedProfileCandidate,
    ProfileMutationPlan,
    RejectedProfileCandidate,
    UserProfileExtractOutput,
    UserProfileItemDTO,
    UserProfileListResponse,
    UserProfileMutationRequest,
    validate_profile_content,
)


class TestUserProfileConstants:
    """验证用户画像枚举与常量。"""

    def test_categories_exist(self):
        assert UserProfileCategory.APPEARANCE.value == "appearance"
        assert UserProfileCategory.PERSONALITY.value == "personality"
        assert UserProfileCategory.LIKES.value == "likes"
        assert UserProfileCategory.DISLIKES.value == "dislikes"
        assert UserProfileCategory.FEARS.value == "fears"
        assert UserProfileCategory.EXPECTATIONS.value == "expectations"
        assert UserProfileCategory.HABITS.value == "habits"
        assert UserProfileCategory.CUSTOM.value == "custom"

    def test_source_types_exist(self):
        assert UserProfileSourceType.MANUAL.value == "manual"
        assert UserProfileSourceType.MODEL_EXTRACTED.value == "model_extracted"

    def test_status_exist(self):
        assert UserProfileStatus.ACTIVE.value == "active"
        assert UserProfileStatus.SUPERSEDED.value == "superseded"
        assert UserProfileStatus.DELETED.value == "deleted"

    def test_cache_status_exist(self):
        assert UserProfileCacheStatus.VALID.value == "valid"
        assert UserProfileCacheStatus.DIRTY.value == "dirty"
        assert UserProfileCacheStatus.MISSING.value == "missing"
        assert UserProfileCacheStatus.REBUILDING.value == "rebuilding"
        assert UserProfileCacheStatus.FAILED.value == "failed"

    def test_default_user_id(self):
        assert USER_PROFILE_DEFAULT_USER_ID == "local_default_user"


class TestUserProfileSchemas:
    """验证用户画像 Pydantic Schema 校验。"""

    def test_valid_mutation_request(self):
        req = UserProfileMutationRequest(
            category=UserProfileCategory.LIKES,
            content="用户喜欢无糖咖啡",
        )
        assert req.content == "用户喜欢无糖咖啡"
        assert req.category == UserProfileCategory.LIKES
        assert req.custom_category_name is None

    def test_mutation_request_content_too_short(self):
        with pytest.raises(ValueError, match="用户画像内容长度"):
            UserProfileMutationRequest(
                category=UserProfileCategory.LIKES,
                content="是",
            )

    def test_mutation_request_content_too_long(self):
        with pytest.raises(ValueError, match="用户画像内容长度"):
            UserProfileMutationRequest(
                category=UserProfileCategory.LIKES,
                content="是" * 300,
            )

    def test_mutation_request_custom_category_required(self):
        with pytest.raises(ValueError, match="自定义类别必须填写类别名称"):
            UserProfileMutationRequest(
                category=UserProfileCategory.CUSTOM,
                content="用户喜欢自定义东西",
                custom_category_name=None,
            )

    def test_valid_extracted_candidate(self):
        candidate = ExtractedProfileCandidate(
            category=UserProfileCategory.LIKES,
            content="用户喜欢无糖咖啡",
            evidence="我平时只喝无糖咖啡",
            confidence=0.92,
            reasoning="用户以第一人称直接陈述长期偏好",
        )
        assert candidate.confidence == 0.92
        assert candidate.source_risk_flags == []

    def test_extracted_candidate_high_risk_low_confidence(self):
        candidate = ExtractedProfileCandidate(
            category=UserProfileCategory.LIKES,
            content="用户喜欢无糖咖啡",
            evidence="我平时只喝无糖咖啡",
            confidence=0.5,
            source_risk_flags=["hypothetical"],
            reasoning="假设场景",
        )
        assert candidate.confidence == 0.5

    def test_extracted_candidate_high_risk_high_confidence_rejected(self):
        with pytest.raises(ValueError, match="高风险标记"):
            ExtractedProfileCandidate(
                category=UserProfileCategory.LIKES,
                content="用户喜欢无糖咖啡",
                evidence="我平时只喝无糖咖啡",
                confidence=0.8,
                source_risk_flags=["sarcasm"],
                reasoning="反讽语气",
            )

    def test_valid_extract_output(self):
        output = UserProfileExtractOutput(session_id="20260607")
        assert output.session_id == "20260607"
        assert output.candidates == []
        assert output.rejected_candidates == []

    def test_extract_output_with_candidates(self):
        output = UserProfileExtractOutput(
            session_id="20260607",
            candidates=[
                ExtractedProfileCandidate(
                    category=UserProfileCategory.LIKES,
                    content="用户喜欢无糖咖啡",
                    evidence="我平时只喝无糖咖啡",
                    confidence=0.92,
                    reasoning="明确偏好",
                )
            ],
        )
        assert len(output.candidates) == 1

    def test_dto_serialization(self):
        dto = UserProfileItemDTO(
            id="123",
            category=UserProfileCategory.LIKES,
            category_label="喜欢的东西",
            content="用户喜欢无糖咖啡",
            source_type=UserProfileSourceType.MANUAL.value,
            confidence=1.0,
            status=UserProfileStatus.ACTIVE.value,
        )
        data = dto.model_dump(mode="json")
        assert data["category"] == "likes"
        assert data["category_label"] == "喜欢的东西"
        assert data["confidence"] == 1.0


class TestUserProfileConflictResolver:
    """验证用户画像冲突处理器。"""

    @pytest.fixture
    def resolver(self):
        return UserProfileConflictResolver()

    def test_normalize_content(self):
        n1 = normalize_profile_content("用户喜欢无糖咖啡")
        n2 = normalize_profile_content("用户喜欢无糖咖啡。")
        assert n1 == n2

    def test_empty_normalize(self):
        assert normalize_profile_content("") == ""

    def test_build_mutation_plan_no_candidates(self, resolver):
        plan = resolver.build_mutation_plan([], [])
        assert isinstance(plan, ProfileMutationPlan)
        assert plan.mutations == []

    def test_add_new_candidate(self, resolver):
        candidate = ExtractedProfileCandidate(
            category=UserProfileCategory.LIKES,
            content="用户喜欢无糖咖啡",
            evidence="我平时只喝无糖咖啡",
            confidence=0.92,
            reasoning="明确偏好",
        )
        plan = resolver.build_mutation_plan([candidate], [])
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == "add"

    def test_reject_low_confidence_candidate(self, resolver):
        """验证置信度低于 0.75 的候选被标记为 reject。"""
        candidate = ExtractedProfileCandidate(
            category=UserProfileCategory.LIKES,
            content="用户喜欢咖啡",
            evidence="我猜他喜欢咖啡不过不能确定是不是每次都真喝",
            confidence=0.60,
            reasoning="语气不太确定但先提出候选",
        )
        plan = resolver.build_mutation_plan([candidate], [])
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == "reject"


class TestUserProfileCache:
    """验证用户画像缓存模块方法签名。"""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.get_client.return_value = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_summary_key(self, mock_redis):
        cache = UserProfileCache(mock_redis)
        key = cache.summary_key("test_user")
        assert "test_user" in key
        assert "summary" in key

    @pytest.mark.asyncio
    async def test_dirty_key(self, mock_redis):
        cache = UserProfileCache(mock_redis)
        key = cache.dirty_key("test_user")
        assert "test_user" in key
        assert "dirty" in key
