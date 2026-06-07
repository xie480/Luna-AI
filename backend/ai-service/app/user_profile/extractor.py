"""
Luna 用户画像提取器。

做什么：组装 user_profile_extract 三槽位 Prompt，调用 LLM 结构化输出并校验候选。
为什么这样做：模型只能提供候选事实，后续写库必须交由服务层和冲突处理器裁决。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from app.config.settings import global_config_container
from app.llm.client import llm_client
from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.models import UserProfileItem
from app.types.constants import ModelSize, Role, UserProfileCategory
from app.user_profile.schemas import UserProfileExtractOutput, category_label


CATEGORY_DEFINITIONS = """
appearance：外貌，只记录用户本人明确描述的外貌特征。
personality：性格，只记录稳定的性格、沟通偏好、行为倾向。
likes：喜欢的东西，只记录长期偏好的食物、风格、活动、作品等。
dislikes：厌恶的东西，只记录稳定反感对象、忌口或不喜欢的事物。
fears：害怕的东西，只记录恐惧或明确回避对象。
expectations：期待的东西，只记录长期愿望、目标或期待被如何对待。
habits：癖好，只记录特殊习惯、偏执偏好或重复行为。
custom：自定义类别，只在标准类别无法表达时使用，并必须提供 custom_category_name。
""".strip()

EXTRACTION_REJECTION_RULES = """
必须拒绝假设、玩笑、反讽、敷衍、引用他人观点、角色扮演、临时情绪、虚构设定、非用户本人陈述、缺少证据的信息。
不确定时宁可不提取；对于“对对对，我超喜欢吃辣，行了吧”这类无奈敷衍或反讽语气，必须拒绝。
""".strip()

OUTPUT_SCHEMA_TEXT = json.dumps(UserProfileExtractOutput.model_json_schema(), ensure_ascii=False, indent=2)


class UserProfileExtractor:
    """
    用户画像提取器。

    做什么：根据会话压缩片段和现有画像生成结构化候选。
    为什么这样做：每次提取前必须全量读取已有画像，避免重复和冲突污染。
    """

    def __init__(self, prompt_manager: PromptManager | None):
        self.prompt_manager = prompt_manager

    async def extract(
        self,
        *,
        session_id: str,
        messages_text: str,
        existing_items: list[UserProfileItem],
        trace_id: str,
    ) -> UserProfileExtractOutput:
        """
        从聊天记录中提取用户画像候选。

        参数:
            session_id: 当前会话ID，用于标识对话会话
            messages_text: 聊天消息文本内容，从中提取用户画像信息
            existing_items: 已存在的用户画像项目列表，用于避免重复提取
            trace_id: 追踪ID，用于日志追踪和调试
        
        返回:
            UserProfileExtractOutput: 包含提取的用户画像候选和被拒绝项的结果对象
        """
        # 检查消息文本是否为空，如果为空则直接返回空结果
        if not messages_text.strip():
            return UserProfileExtractOutput(session_id=session_id)
        
        # 组装提示词，结合会话ID、消息文本和已存在项目
        prompt = await self._assemble_prompt(session_id, messages_text, existing_items)
        
        # 获取小尺寸模型配置
        config = global_config_container.get_model_config(ModelSize.SMALL)
        model = config.get("model_id") or llm_client.model_name
        
        # 构建消息格式供LLM处理
        messages = [{"role": Role.SYSTEM.value, "content": prompt}]
        
        # 调用LLM进行结构化生成，设置超时时间
        result = await asyncio.wait_for(
            llm_client.generate_structured(
                model=model,
                messages=messages,
                response_format=UserProfileExtractOutput,
                timeout=30.0,
            ),
            timeout=35.0,
        )
        
        # 确保结果是UserProfileExtractOutput类型
        if not isinstance(result, UserProfileExtractOutput):
            result = UserProfileExtractOutput.model_validate(result)
        
        # 记录提取完成的日志信息
        logger.info(
            f"用户画像提取完成 trace_id={trace_id} session_id={session_id} "
            f"candidates={len(result.candidates)} rejected={len(result.rejected_candidates)}"
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
            "CATEGORY_DEFINITIONS": CATEGORY_DEFINITIONS,
            "EXTRACTION_REJECTION_RULES": EXTRACTION_REJECTION_RULES,
            "SESSION_ID": session_id,
            "MESSAGES_TEXT": messages_text,
            "CURRENT_TIME": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "OUTPUT_SCHEMA": OUTPUT_SCHEMA_TEXT,
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
            lines.append(f"- [{label}] {item.content}（置信度 {float(item.confidence):.2f}，ID {item.id}）")
        return "\n".join(lines)
