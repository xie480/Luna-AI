"""
Luna 用户画像冲突处理工具。

做什么：提供用户画像正文归一化函数。
为什么这样做：手动录入与模型写库前都需要统一的轻量归一化规则。
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
    边界条件：空字符串返回空字符串。
    异常行为：无。
    """
    return _PUNCTUATION_PATTERN.sub("", content.strip().lower())
