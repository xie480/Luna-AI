from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import llm_client
from app.logger import logger


class EvaluationResult(BaseModel):
    is_met: bool = Field(..., description="目标是否达成。")
    suggestion: str = Field(
        default="",
        description="如果未达成，给出针对下一轮参数调整的自然语言建议（例如：“当前检索未发现2024年的数据，请尝试在查询词中加入'2024'并换用英文重试”）。如果达成，可以为空。",
    )

class MCPEvaluationAgent:
    """MCP 意图达成评估 Agent。"""

    @property
    def model_name(self) -> str:
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def evaluate(
        self,
        trace_id: str,
        mcp_intent: str,
        step_goal: str,
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        评估工具执行结果是否达成了用户的意图和步骤目标。
        """
        started_at = time.monotonic()
        
        # 组装输出文本用于评估，适当截断防止 token 爆炸
        results_text_parts = []
        for r in tool_results:
            if r.get("success"):
                results_text_parts.append(f"[工具 {r.get('tool_name')} 输出]:\n{r.get('output_text', '')[:4000]}")
            else:
                results_text_parts.append(f"[工具 {r.get('tool_name')} 错误]:\n{r.get('error_message', '')}")
                
        results_text = "\n\n".join(results_text_parts)
        if not results_text:
            results_text = "（无工具执行结果）"

        system_prompt = (
            "你是一个严格的执行结果评估器。你需要评估刚才执行的工具结果是否满足了原始意图。\n"
            "判断规则：\n"
            "1. 仔细阅读「工具执行结果」。\n"
            "2. 如果结果中包含能够解决「用户初始意图」或「步骤目标」的核心信息，即使信息不完美，也认为 is_met=true。\n"
            "3. 如果结果完全无关、无数据、报错，或者明确表示缺少所需信息，则 is_met=false。\n"
            "4. 如果 is_met=false，必须在 suggestion 字段中给出具体的、可操作的下一轮策略调整建议（比如换关键词、换语言、扩大范围）。"
        )
        
        user_prompt = (
            f"【用户初始意图】\n{mcp_intent}\n\n"
            f"【当前步骤目标】\n{step_goal}\n\n"
            f"【工具执行结果】\n{results_text}"
        )

        logger.info(f"[MCP Evaluation Agent] 开始评估 trace_id={trace_id}")

        try:
            response = await llm_client.generate_structured(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=EvaluationResult,
                timeout=30.0,
            )
            
            elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
            logger.info(
                f"[MCP Evaluation Agent] 评估完成 trace_id={trace_id} "
                f"is_met={response.is_met} latency_ms={elapsed_ms}"
            )
            
            return {
                "is_met": response.is_met,
                "suggestion": response.suggestion,
                "latency_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.warning(
                f"MCP Evaluation Agent 评估失败 trace_id={trace_id} error={exc!s}"
            )
            return {
                "is_met": False,
                "suggestion": f"评估失败：{exc!s}。请尝试调整策略重新执行。",
                "latency_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            }
