"""
Luna 用户画像提取器。

做什么：组装 user_profile_extract 三槽位 Prompt，调用 LLM 直接输出可提交的用户画像变更计划。
为什么这样做：重复和冲突由模型结合已有画像在提取阶段一次性决策，后端不再做低效的关键词冲突判断。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.config.settings import global_config_container
from app.llm.client import llm_client
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.models import UserProfileItem
from app.types.constants import ModelSize, Role
from app.user_profile.schemas import ProfileMutationPlan, category_label


class UserProfileExtractor:
    """用户画像提取器。"""

    def __init__(self, prompt_manager: PromptManager | None):
        self.prompt_manager = prompt_manager

    async def extract(
        self,
        *,
        session_id: str,
        messages_text: str,
        existing_items: list[UserProfileItem],
        trace_id: str,
    ) -> ProfileMutationPlan:
        """从聊天记录中提取可直接提交的用户画像变更计划。"""
        if not messages_text.strip():
            return ProfileMutationPlan()
        prompt = await self._assemble_prompt(session_id, messages_text, existing_items)
        config = global_config_container.get_model_config(ModelSize.SMALL)
        model = config.get("model_id") or llm_client.model_name
        messages = [{"role": Role.SYSTEM.value, "content": prompt}]
        result = await asyncio.wait_for(
            llm_client.generate_structured(
                model=model,
                messages=messages,
                response_format=ProfileMutationPlan,
                timeout=30.0,
            ),
            timeout=35.0,
        )
        if not isinstance(result, ProfileMutationPlan):
            result = ProfileMutationPlan.model_validate(result)
        logger.info(
            f"用户画像变更计划提取完成 trace_id={trace_id} session_id={session_id} "
            f"mutations={len(result.mutations)}"
        )
        return result

    async def _assemble_prompt(
        self,
        session_id: str,
        messages_text: str,
        existing_items: list[UserProfileItem],
    ) -> str:
        """组装用户画像提取 Prompt。"""
        if not self.prompt_manager:
            raise RuntimeError("Prompt 管理器不可用，无法提取用户画像")
        variables = {
            "EXISTING_USER_PROFILES": self._format_existing_items(existing_items),
            "SESSION_ID": session_id,
            "MESSAGES_TEXT": messages_text,
            "CURRENT_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        prompt = await self.prompt_manager.assemble_prompt(PromptCategory.USER_PROFILE_EXTRACT, variables)
        if not prompt.strip():
            raise RuntimeError("用户画像提取 Prompt 为空")
        return prompt

    def _format_existing_items(self, items: list[UserProfileItem]) -> str:
        """按类别格式化已有 active 用户画像。"""
        if not items:
            return "当前没有已入库的用户画像。"
        lines: list[str] = []
        for item in items:
            label = category_label(item.category, item.custom_category_name)
            lines.append(
                f"- ID: {item.id}；类别: {label}；内容: {item.content}；"
                f"置信度: {float(item.confidence):.2f}；状态: {item.status}"
            )
        return "\n".join(lines)
