from __future__ import annotations

import json
import time
from typing import Any

from app.llm.client import llm_client
from app.logger import logger


class MCPSkillMemoryAgent:
    """MCP 技能记忆提取 Agent。
    
    做什么：在多轮执行内层循环中，基于历史执行数据、上一轮的评估建议，
            以及当前技能声明的 memory_schema，动态提取并输出一组键值对。
            这些键值对将用于渲染该技能专属的 memory.j2。
    """

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
        """
        started_at = time.monotonic()
        
        # 组装上下文：历史的所有参数、结果等
        # 适当截断以防止 Token 超限
        context_str = json.dumps(all_round_data, ensure_ascii=False)
        if len(context_str) > 8000:
            context_str = context_str[-8000:]
            
        system_prompt = (
            f"你是一个用于 '{skill_name}' 技能的状态提取分析器。\n"
            f"用户的初始意图是: {mcp_intent}\n"
            "以下是该技能过去的执行日志。请分析执行日志，判断当前的信息缺口，"
            "并严格按照提供的 JSON Schema 输出记忆状态变量字典。\n"
            "这些变量将用于指导下一轮该技能的执行。"
        )
        
        if inner_suggestion:
            system_prompt += f"\n\n注意：上一轮执行后的评估建议是：{inner_suggestion}。请务必在提取策略变量时参考此建议。"
            
        logger.info(
            f"[MCP Skill Memory Agent] 开始提取 trace_id={trace_id} "
            f"skill_name={skill_name} suggestion={inner_suggestion}"
        )

        try:
            response = await llm_client.generate_structured(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"历史执行日志:\n{context_str}"},
                ],
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
