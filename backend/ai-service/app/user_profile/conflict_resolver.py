"""
Luna 用户画像冲突处理工具。

做什么：提供用户画像正文归一化与轻量冲突判断能力。
为什么这样做：手动录入、模型写库和启动依赖注入都需要统一的冲突处理入口，避免规则散落。
"""

from __future__ import annotations

import re

_PUNCTUATION_PATTERN = re.compile(r"[\s\t\r\n，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]{}<>《》—_-]+")


def normalize_profile_content(content: str) -> str:
    """
    归一化用户画像正文。

    做什么：去除空白、常见标点并转小写，用于手动录入去重和写库前标准化。
    为什么这样做：避免轻微格式差异导致重复条目。
    输入输出：输入画像正文，输出归一化文本。
    边界条件：空字符串返回空字符串；非字符串输入抛出明确异常。
    异常行为：当调用方传入非字符串时抛出 TypeError，避免无效画像内容静默进入去重链路。
    """
    if not isinstance(content, str):
        raise TypeError("用户画像正文必须是字符串")
    return _PUNCTUATION_PATTERN.sub("", content.strip().lower())


class UserProfileConflictResolver:
    """
    用户画像冲突解析器。

    做什么：封装用户画像归一化与重复判断规则。
    为什么这样做：主启动流程需要注入冲突解析器实例，服务层也需要统一入口执行去重，避免导入缺失和规则分裂。
    输入输出：输入已有画像字段与候选画像正文，输出标准化文本或重复判断布尔值。
    边界条件：空正文会归一化为空字符串；类别或标准化内容为空时不会误判为重复。
    异常行为：正文类型不合法时由 normalize_profile_content 抛出 TypeError，由上层 API 校验或任务日志解释。
    """

    def normalize_content(self, content: str) -> str:
        """
        归一化候选画像正文。

        做什么：对外暴露实例方法，复用模块级归一化函数。
        为什么这样做：便于服务层通过依赖注入使用同一套规则，也保留旧测试直接调用函数的能力。
        输入输出：输入原始正文，输出归一化后的正文。
        边界条件：空字符串返回空字符串。
        异常行为：非字符串输入抛出 TypeError。
        """
        return normalize_profile_content(content)

    def is_duplicate(
        self,
        *,
        existing_category: str,
        existing_normalized_content: str,
        candidate_category: str,
        candidate_content: str,
    ) -> bool:
        """
        判断候选画像是否与已有画像重复。

        做什么：比较类别和归一化正文是否完全一致。
        为什么这样做：重复判断只允许在同类别内生效，避免不同类别下的相似文本互相覆盖。
        输入输出：输入已有画像类别、已有归一化正文、候选类别和候选正文，输出是否重复。
        边界条件：类别或归一化正文为空时返回 False，避免空值误伤。
        异常行为：候选正文非字符串时抛出 TypeError。
        """
        if not existing_category or not existing_normalized_content or not candidate_category:
            return False
        candidate_normalized = self.normalize_content(candidate_content)
        if not candidate_normalized:
            return False
        return existing_category == candidate_category and existing_normalized_content == candidate_normalized
