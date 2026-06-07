"""
Luna 用户画像摘要生成器。

做什么：将 PostgreSQL 中 active 用户画像压缩为适合注入 Chat Prompt 的短文本。
为什么这样做：聊天链路只读取 Redis 压缩摘要，避免每轮全量扫描数据库。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.llm.client import llm_client
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.models import UserProfileItem
from app.types.constants import ModelSize, Role
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
        """生成用户画像压缩摘要。"""
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
        from app.config.settings import global_config_container

        config = global_config_container.get_model_config(ModelSize.SMALL)
        model = config.get("model_id") or llm_client.model_name
        messages = [{"role": Role.SYSTEM.value, "content": prompt}]
        summary = await asyncio.wait_for(
            llm_client.generate_structured_text(model=model, messages=messages, timeout=30.0),
            timeout=35.0,
        )
        summary_text = summary.strip()
        if not summary_text:
            raise RuntimeError("用户画像摘要模型返回空文本")
        logger.info(f"用户画像摘要生成完成 trace_id={trace_id} items_count={len(items)} summary_length={len(summary_text)}")
        return summary_text[:2000]

    def _format_items(self, items: list[UserProfileItem]) -> str:
        """按类别格式化 active 用户画像。"""
        lines: list[str] = []
        for item in items:
            label = category_label(item.category, item.custom_category_name)
            confidence = float(item.confidence)
            lines.append(f"- 类别：{label}；内容：{item.content}；置信度：{confidence:.2f}")
        return "\n".join(lines)
