from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import llm_client
from app.logger import logger
from app.prompt.types import PromptCategory


class EvaluationResult(BaseModel):
    """评估结果结构。"""
    is_met: bool = Field(..., description="目标是否达成。")
    suggestion: str = Field(
        default="",
        description="如果未达成，给出针对下一轮参数调整的自然语言建议。如果达成，可以为空。",
    )
    reply: str = Field(
        default="",
        description="Luna 面向主人的简短回应文本。用于同步当前步骤执行状态、表达看法或情绪。"
                    "不得回答用户问题，不得总结任务结果，不得复述工具结果。",
    )
    emotion: str = Field(
        default="",
        description="Luna 当前情绪状态。必须从情绪枚举中选择一个最符合当前 reply 的情绪。"
                    "情绪应与执行结果和上下文保持一致，不得随机选择。",
    )


class MCPEvaluationAgent:
    """MCP 意图达成评估 Agent。"""

    def __init__(self, prompt_manager: Any = None) -> None:
        self.prompt_manager = prompt_manager

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

        参数:
            trace_id: 全链路追踪 ID。
            mcp_intent: 用户初始意图。
            step_goal: 当前步骤目标。
            tool_results: 已执行的工具结果列表。
        返回:
            dict: is_met (bool), suggestion (str), reply (str), emotion (str), latency_ms (int)。
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

        # 使用 PromptManager 组装三槽位提示
        system_prompt = ""
        memory_prompt = ""
        runtime_prompt = ""
        full_prompt = ""
        if self.prompt_manager:
            try:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
                full_prompt = await self.prompt_manager.assemble_prompt(
                    PromptCategory.MCP_EVALUATION,
                    {
                        "CURRENT_TIME": current_time,
                        "MCP_INTENT": mcp_intent,
                        "STEP_GOAL": step_goal,
                        "EXECUTION_RESULTS": results_text,
                    },
                )
            except Exception:
                pass

        # 兜底：如果 full_prompt 为空（如 prompt_manager 未注入），使用默认评估提示，
        # 避免发空内容给大模型引发 "contents field is required" 错误
        effective_prompt = full_prompt or "请根据工具执行结果评估用户意图是否达成。"
        logger.info(f"[MCP Evaluation Agent] 开始评估 trace_id={trace_id}, full_prompt={effective_prompt}")
        try:
            response = await llm_client.generate_structured(
                model=self.model_name,
                messages=[{"role": "system", "content": effective_prompt}],
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
                "reply": response.reply,
                "emotion": response.emotion,
                "latency_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.warning(
                f"MCP Evaluation Agent 评估失败 trace_id={trace_id} error={exc!s}"
            )
            return {
                "is_met": False,
                "suggestion": f"评估失败：{exc!s}。请尝试调整策略重新执行。",
                "reply": "",
                "emotion": "",
                "latency_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            }
