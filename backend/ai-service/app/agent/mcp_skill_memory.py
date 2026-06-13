from __future__ import annotations

import json
import time
from typing import Any

from app.llm.client import llm_client
from app.logger import logger
from app.prompt.types import PromptCategory


class MCPSkillMemoryAgent:
    """MCP 技能记忆提取 Agent。

    做什么：在多轮执行内层循环中，基于历史执行数据、上一轮的评估建议，
            以及当前技能声明的 memory_schema，动态提取并输出一组键值对。
            这些键值对将用于渲染该技能专属的 memory.j2。
    """

    def __init__(self, prompt_manager: Any = None) -> None:
        self.prompt_manager = prompt_manager

    @property
    def model_name(self) -> str:
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def extract_memory_variables(
        self,
        trace_id: str,
        skill_name: str,
        memory_schema: dict[str, Any],
        mcp_intent: str,
        all_round_data: list[dict[str, Any]],
        inner_suggestion: str = "",
    ) -> dict[str, Any]:
        """
        基于 Schema 动态提取特定技能的记忆变量。

        参数:
            trace_id: 全链路追踪 ID。
            skill_name: 技能名称。
            memory_schema: 该技能声明的 memory_schema JSON Schema。
            mcp_intent: 用户的初始意图。
            all_round_data: 所有轮次的历史执行数据。
            inner_suggestion: 上一轮评估给出的建议。
        返回:
            dict: 符合 memory_schema 结构的键值对集合。
        """
        started_at = time.monotonic()

        # 组装上下文：历史的所有参数、结果等
        context_str = json.dumps(all_round_data, ensure_ascii=False)
        if len(context_str) > 8000:
            context_str = context_str[-8000:]

        # 使用 PromptManager 组装三槽位提示
        system_prompt = ""
        memory_prompt = ""
        runtime_prompt = ""
        if self.prompt_manager:
            try:
                system_prompt = await self.prompt_manager.assemble_prompt(
                    PromptCategory.MCP_SKILL_MEMORY,
                    {
                        "SKILL_NAME": skill_name,
                        "MCP_INTENT": mcp_intent,
                        "INNER_SUGGESTION": inner_suggestion or "",
                    },
                )
                memory_prompt = await self.prompt_manager.assemble_prompt(
                    PromptCategory.MCP_SKILL_MEMORY,
                    {
                        "EXECUTION_HISTORY_CONTEXT": context_str,
                    },
                )
                runtime_prompt = await self.prompt_manager.assemble_prompt(
                    PromptCategory.MCP_SKILL_MEMORY,
                    {
                        "MEMORY_SCHEMA": json.dumps(memory_schema, ensure_ascii=False, indent=2),
                    },
                )
            except Exception:
                pass

        # 回退：如果 prompt_manager 不可用，使用旧的硬编码形式
        if not system_prompt:
            system_prompt = (
                f"你是一个专门用于 {skill_name} 技能的状态提取与分析引擎。\n\n"
                f"用户的最终目标意图是：{mcp_intent}\n\n"
                "【任务说明】\n"
                "系统已经执行了若干轮的工具调用。你的任务是基于历史的执行日志，仔细分析当前的进展，"
                "寻找仍未解决的信息缺口，并推演下一步最优的执行策略。\n\n"
                "【执行要求】\n"
                "1. 严格遵守传入的 JSON Schema 格式输出对应的变量键值对。\n"
                "2. 输出的变量将直接被注入到下一轮工具调用的上下文中，请确保内容精炼、准确且具有指导性。\n"
                "3. 提取历史记录时，注意区分失败的尝试和部分成功的成果，不要重复走弯路。\n"
            )
            if inner_suggestion:
                system_prompt += (
                    f"\n注意：上一轮执行后的评估建议是：{inner_suggestion}。"
                    "请务必在提取策略变量时参考此建议。"
                )
            context_section = f"\n\n【历史执行日志】\n{context_str}"
            memory_prompt = context_section
            runtime_prompt = (
                "请根据以上数据和指示，严格按照以下 JSON Schema 输出记忆状态变量字典：\n\n"
                f"{json.dumps(memory_schema, ensure_ascii=False, indent=2)}"
            )

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        logger.info(
            f"[MCP Skill Memory Agent] 开始提取 trace_id={trace_id} "
            f"skill_name={skill_name} suggestion={inner_suggestion}"
        )

        try:
            response = await llm_client.generate_structured(
                model=self.model_name,
                messages=[{"role": "system", "content": full_prompt}],
                response_format=memory_schema,
                timeout=30.0,
            )

            elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
            logger.info(
                f"[MCP Skill Memory Agent] 提取完成 trace_id={trace_id} "
                f"latency_ms={elapsed_ms}"
            )

            # response 是一个 BaseModel 或 dict，如果是 BaseModel，转换为 dict
            if hasattr(response, "model_dump"):
                return response.model_dump(mode="json")
            return dict(response)

        except Exception as exc:
            logger.warning(
                f"MCP Skill Memory Agent 提取失败 trace_id={trace_id} error={exc!s}"
            )
            # 提取失败时返回空字典，防止阻断流程
            return {}
