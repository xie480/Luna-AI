"""
Luna 用户画像摘要生成器。

做什么：将 PostgreSQL 中 active 用户画像压缩为适合注入 Chat Prompt 的短文本。
为什么这样做：聊天链路只读取 Redis 压缩摘要，避免每轮全量扫描数据库。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from openai import APIConnectionError, APITimeoutError

from app.llm.client import compression_llm_client
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.models import UserProfileItem

from app.types.constants import (
    USER_PROFILE_SUMMARY_FALLBACK_MAX_ITEMS,
    USER_PROFILE_SUMMARY_MAX_LENGTH,
    USER_PROFILE_SUMMARY_MODEL_TIMEOUT_SECONDS,
    Role,
)
from app.user_profile.schemas import category_label


class UserProfileSummarizer:
    """
    用户画像摘要生成器。

    做什么：读取 active 条目列表，组装 user_profile_summarize Prompt 并调用结构化模型生成摘要文本。
    为什么这样做：摘要文本必须由 Agent 按类别压缩，而不是简单拼接数据库全文。
    """

    def __init__(self, prompt_manager: PromptManager | None):
        self.prompt_manager = prompt_manager

    async def summarize(self, items: list[UserProfileItem], trace_id: str) -> str:
        """
        生成用户画像压缩摘要。

        做什么：优先调用小模型把 active 用户画像压缩为 Prompt 摘要，模型网络超时或连接失败时回退到本地摘要。
        为什么这样做：用户画像摘要属于聊天链路的辅助上下文，不能因为后台模型连接慢而把缓存重建标记为错误。
        输入输出：输入数据库画像条目和 trace_id，输出最长 USER_PROFILE_SUMMARY_MAX_LENGTH 的摘要文本。
        边界条件：无画像返回空字符串；模型返回空文本或网络不可用时使用确定性本地摘要兜底。
        异常行为：任务取消继续向上抛出；Prompt 配置缺失属于配置错误，继续抛出明确异常。
        """
        if not items:
            return ""
        profile_text = self._format_items(items)
        variables = {
            "USER_PROFILE_ITEMS": profile_text,
            "CURRENT_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if not self.prompt_manager:
            raise RuntimeError("Prompt 管理器不可用，无法生成用户画像摘要")
        prompt = await self.prompt_manager.assemble_prompt(PromptCategory.USER_PROFILE_SUMMARIZE, variables)
        if not prompt.strip():
            raise RuntimeError("用户画像摘要 Prompt 为空")
        messages = [{"role": Role.SYSTEM.value, "content": prompt}]
        try:
            summary = await compression_llm_client.summarize_once(
                messages=messages,
                timeout=USER_PROFILE_SUMMARY_MODEL_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, APIConnectionError, APITimeoutError) as exc:
            summary = self._build_fallback_summary(items)
            logger.warning(
                f"用户画像摘要模型调用失败，已使用本地摘要兜底 trace_id={trace_id} "
                f"items_count={len(items)} timeout_seconds={USER_PROFILE_SUMMARY_MODEL_TIMEOUT_SECONDS} "
                f"error_type={type(exc).__module__}.{type(exc).__qualname__} error_message={str(exc) or '<空异常消息>'}"
            )
        summary_text = summary.strip()
        if not summary_text:
            summary_text = self._build_fallback_summary(items)
        if not summary_text:
            raise RuntimeError("用户画像摘要模型返回空文本且本地兜底摘要为空")
        logger.info(f"用户画像摘要生成完成 trace_id={trace_id} items_count={len(items)} summary_length={len(summary_text)}")
        return summary_text[:USER_PROFILE_SUMMARY_MAX_LENGTH]

    def _format_items(self, items: list[UserProfileItem]) -> str:
        """
        按类别格式化 active 用户画像。

        做什么：把数据库画像条目转换为模型可读的项目符号文本。
        为什么这样做：统一 Prompt 输入格式，避免摘要模型误读字段边界。
        输入输出：输入画像 ORM 列表，输出包含类别、内容和置信度的多行文本。
        边界条件：空列表返回空字符串；置信度会显式格式化为两位小数。
        异常行为：字段缺失时让调用方看到原始异常，避免静默生成错误摘要。
        """
        lines: list[str] = []
        for item in items:
            label = category_label(item.category, item.custom_category_name)
            confidence = float(item.confidence)
            lines.append(f"- 类别：{label}；内容：{item.content}；置信度：{confidence:.2f}")
        return "\n".join(lines)

    def _build_fallback_summary(self, items: list[UserProfileItem]) -> str:
        """
        构建确定性的本地兜底摘要。

        做什么：在小模型连接超时、网络失败或返回空文本时，按类别拼接有限数量的画像条目。
        为什么这样做：缓存重建必须可恢复；本地摘要虽然不如模型压缩自然，但能保证聊天链路继续可用。
        输入输出：输入 active 画像条目，输出可直接注入 Prompt 的中文摘要。
        边界条件：只保留 USER_PROFILE_SUMMARY_FALLBACK_MAX_ITEMS 条，最终仍按最大摘要长度截断。
        异常行为：本方法不访问外部资源，不主动抛出业务异常。
        """
        grouped: dict[str, list[str]] = {}
        for item in items[:USER_PROFILE_SUMMARY_FALLBACK_MAX_ITEMS]:
            label = category_label(item.category, item.custom_category_name)
            grouped.setdefault(label, []).append(str(item.content).strip())
        lines = ["用户画像摘要（本地兜底生成）："]
        for label, contents in grouped.items():
            filtered_contents = [content for content in contents if content]
            if filtered_contents:
                lines.append(f"- {label}：{'；'.join(filtered_contents)}")
        return "\n".join(lines)[:USER_PROFILE_SUMMARY_MAX_LENGTH]
