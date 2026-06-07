"""
Luna 用户画像冲突处理器。

做什么：提供画像正文归一化、重复检测、保守冲突识别和变更计划生成。
为什么这样做：模型只能产出候选，是否写库必须由 Python 后端基于现有画像统一裁决。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.repository.models import UserProfileItem
from app.types.constants import USER_PROFILE_MUTATION_SCHEMA_VERSION, UserProfileCategory
from app.user_profile.schemas import ExtractedProfileCandidate, ProfileMutation, ProfileMutationPlan

_NEGATIVE_MARKERS = ("不喜欢", "讨厌", "厌恶", "不吃", "不喝", "害怕", "恐惧", "回避")
_POSITIVE_MARKERS = ("喜欢", "期待", "希望", "爱吃", "爱喝", "偏好")
_PUNCTUATION_PATTERN = re.compile(r"[\s\t\r\n，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]{}<>《》—_-]+")


def normalize_profile_content(content: str) -> str:
    """
    归一化用户画像正文。

    做什么：去除空白、常见标点并转小写，用于重复检测。
    为什么这样做：避免同义轻微格式差异造成重复入库。
    输入输出：输入画像正文，输出归一化文本。
    边界条件：空字符串返回空字符串。
    异常行为：无。
    """
    return _PUNCTUATION_PATTERN.sub("", content.strip().lower())


class UserProfileConflictResolver:
    """
    用户画像冲突处理器。

    做什么：根据现有 active 画像和新候选生成内部变更计划。
    为什么这样做：数据库提交前必须执行重复检测和冲突处理，避免画像污染。
    """

    def build_mutation_plan(
        self,
        candidates: list[ExtractedProfileCandidate],
        existing_items: list[UserProfileItem],
    ) -> ProfileMutationPlan:
        """生成用户画像变更计划。

        Args:
            candidates (list[ExtractedProfileCandidate]): 待处理的画像候选列表
            existing_items (list[UserProfileItem]): 已存在的用户画像项目列表

        Returns:
            ProfileMutationPlan: 包含所有变更操作的画像变更计划
        """
        mutations: list[ProfileMutation] = []
        # 遍历所有候选项目，确定每个项目的处理方式
        for candidate in candidates:
            # 检查候选置信度是否低于自动入库阈值
            if candidate.confidence < 0.75:
                mutations.append(ProfileMutation(action="reject", candidate=candidate, reason="候选置信度低于自动入库阈值"))
                continue
            # 筛选出相同分类的已有项目
            same_category_items = [item for item in existing_items if item.category == candidate.category.value]
            # 查找是否存在重复项目
            duplicate_item = self._find_duplicate(candidate, same_category_items)
            if duplicate_item:
                # 如果是重复项目，确认已存在项目并更新其确认时间
                mutations.append(ProfileMutation(
                    action="confirm_existing",
                    candidate=candidate,
                    target_item_id=duplicate_item.id,
                    reason="新候选与已有画像高度重复，更新最近确认时间",
                ))
                continue
            # 查找是否存在冲突项目
            conflict_item = self._find_conflict(candidate, same_category_items)
            if conflict_item:
                # 如果存在冲突，用新的可信版本替代旧版本
                mutations.append(ProfileMutation(
                    action="supersede",
                    candidate=candidate,
                    target_item_id=conflict_item.id,
                    reason="新候选与已有画像存在前后冲突，采用最新可信版本",
                ))
                continue
            # 如果没有问题，直接添加新画像
            mutations.append(ProfileMutation(action="add", candidate=candidate, reason="新画像"))
        return ProfileMutationPlan(schema_version=USER_PROFILE_MUTATION_SCHEMA_VERSION, mutations=mutations)

    def _find_duplicate(
        self,
        candidate: ExtractedProfileCandidate,
        existing_items: list[UserProfileItem],
    ) -> UserProfileItem | None:
        """查找重复或高度相似的画像。

        该方法通过多种策略检测新候选画像与现有画像之间的重复性：
        1. 完全匹配：检查归一化后的内容是否完全相等
        2. 包含关系：检查一个内容是否包含另一个内容
        3. 相似度匹配：使用SequenceMatcher计算内容相似度，超过95%则认为是重复
        
        Args:
            candidate (ExtractedProfileCandidate): 待检测的画像候选对象，包含内容、分类等信息
            existing_items (list[UserProfileItem]): 已存在的画像项目列表，用于与候选进行比较
        
        Returns:
            UserProfileItem | None: 如果找到重复或高度相似的画像则返回该画像对象，
                                   否则返回None
        """
        # 对候选内容进行归一化处理，去除标点和空格以便比较
        normalized = normalize_profile_content(candidate.content)
        # 遍历所有现有项目，逐个进行重复性检查
        for item in existing_items:
            # 获取现有项目的归一化内容，如果未缓存则进行归一化处理
            existing_normalized = item.normalized_content or normalize_profile_content(item.content)
            # 检查是否完全相同
            if normalized == existing_normalized:
                return item
            # 检查是否存在包含关系（一个内容是另一个的子集）
            if normalized in existing_normalized or existing_normalized in normalized:
                return item
            # 使用序列匹配算法计算内容相似度
            similarity = SequenceMatcher(None, normalized, existing_normalized).ratio()
            # 如果相似度达到95%以上，则认为是重复内容
            if similarity >= 0.95:
                return item
        # 如果遍历完所有现有项目都没有发现重复，则返回None
        return None

    def _find_conflict(
        self,
        candidate: ExtractedProfileCandidate,
        existing_items: list[UserProfileItem],
    ) -> UserProfileItem | None:
        """保守识别同类别中正负倾向相反且主体相似的冲突画像。
        
        该方法通过以下步骤检测潜在冲突的画像：
        1. 分析候选画像的情感极性（正面/负面/中性）
        2. 过滤掉中性画像（因为无法构成冲突）
        3. 提取候选画像的核心主题内容（去除情感标记词）
        4. 遍历现有的同类别画像项目
        5. 比较现有画像与候选画像的情感极性是否相反
        6. 计算两者核心主题内容的相似度，若达到阈值则判定为冲突
        
        Args:
            candidate (ExtractedProfileCandidate): 待检测冲突的画像候选对象，包含内容、分类等信息
            existing_items (list[UserProfileItem]): 已存在的同类别画像项目列表，用于与候选进行冲突比较
        
        Returns:
            UserProfileItem | None: 如果找到与候选画像存在冲突的现有项目则返回该画像对象，
                                   否则返回None。冲突定义为：同类别、情感极性相反、主体内容相似度>=0.70
        """
        # 对候选内容进行归一化处理，去除标点和空格以便后续比较
        candidate_normalized = normalize_profile_content(candidate.content)
        # 分析候选画像的情感极性（正面/负面/中性）
        candidate_polarity = self._polarity(candidate_normalized, candidate.category)
        # 如果候选画像为中性，则无法构成冲突，直接返回None
        if candidate_polarity == "neutral":
            return None
        # 提取候选画像的核心主题内容（去除情感标记词）
        candidate_subject = self._strip_markers(candidate_normalized)
        # 遍历所有现有的同类别画像项目
        for item in existing_items:
            # 获取现有项目的归一化内容，如果未缓存则进行归一化处理
            existing_normalized = item.normalized_content or normalize_profile_content(item.content)
            # 分析现有画像的情感极性
            existing_polarity = self._polarity(existing_normalized, candidate.category)
            # 如果现有画像是中性或与候选画像极性相同，则跳过（不构成冲突）
            if existing_polarity == "neutral" or existing_polarity == candidate_polarity:
                continue
            # 提取现有画像的核心主题内容（去除情感标记词）
            existing_subject = self._strip_markers(existing_normalized)
            # 使用序列匹配算法计算两个画像核心内容的相似度
            if SequenceMatcher(None, candidate_subject, existing_subject).ratio() >= 0.70:
                # 如果相似度达到70%及以上，则认为存在冲突，返回该现有画像项目
                return item
        # 如果遍历完所有现有项目都没有发现冲突，则返回None
        return None

    def _polarity(self, normalized_content: str, category: UserProfileCategory) -> str:
        """判断画像语义倾向。"""
        if any(marker in normalized_content for marker in _NEGATIVE_MARKERS):
            return "negative"
        if category in (UserProfileCategory.DISLIKES, UserProfileCategory.FEARS):
            return "negative"
        if any(marker in normalized_content for marker in _POSITIVE_MARKERS):
            return "positive"
        if category in (UserProfileCategory.LIKES, UserProfileCategory.EXPECTATIONS):
            return "positive"
        return "neutral"

    def _strip_markers(self, normalized_content: str) -> str:
        """移除正负倾向词后得到粗略主体。"""
        result = normalized_content
        for marker in (*_NEGATIVE_MARKERS, *_POSITIVE_MARKERS, "用户", "现在", "以前", "最近"):
            result = result.replace(marker, "")
        return result
