"""
MCP 意图对齐 Agent（Agent 3）。

做什么：接收工具执行网关返回的原始结果，结合原始用户意图进行校准、打磨与逻辑重组，
        输出高质量最终文本。
为什么这样做：工具返回的原始数据可能包含冗余、非结构化或不完全匹配用户需求的内容，
            需要 LLM 进行意图对齐后再注入下游 Prompt 以避免污染。
边界条件：
    - LLM 调用失败重试 2 次，重试耗尽后直接使用工具原始输出（标记 quality_issue=True）。
    - calibrated_output 禁止包含工具返回中不存在的虚构信息。
    - 支持单工具和多工具聚合结果的意图对齐。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.types import IntentAlignmentResult
from app.prompt.types import PromptCategory


class MCPIntentAlignmentAgent:
    """MCP 意图对齐 Agent。

    做什么：对工具执行结果进行意图校准和输出质量把控。
    为什么这样做：作为 MCP 工具链路的最终质量门禁，确保下游节点接收到的
                是经过语义对齐的高质量数据。
    """

    def __init__(self) -> None:
        """
        初始化意图对齐 Agent。

        做什么：设置最大重试次数。
        为什么这样做：max_retries=2 确保 LLM 调用有有限容错。
        """
        self.max_retries = 2

    @property
    def model_name(self) -> str:
        """
        获取当前配置的中模型名称。

        做什么：从全局配置容器中读取 MEDIUM 模型的 model_id。
        为什么这样做：Agent 3 使用中模型，在输出质量和成本之间取得平衡。
        返回:
            str: 模型 ID，如 "gpt-4o-mini"。配置不存在时返回默认值。
        """
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def align(
        self,
        trace_id: str,
        user_input: str,
        intent_summary: str,
        tool_name: str,
        tool_raw_output: str,
        tool_latency_ms: int,
        tool_risk_level: str,
        prompt_manager: Any,
    ) -> IntentAlignmentResult:
        """
        执行意图对齐与输出校准。

        做什么：1. 组装三槽位 Prompt（system + memory + runtime）。
                2. 调用 LLM 对工具原始输出进行校准、打磨和逻辑重组。
                3. 输出 IntentAlignmentResult（含质量判定）。
        参数:
            trace_id: 全链路追踪 ID。
            user_input: 用户原始输入。
            intent_summary: 输入重构节点的意图摘要。
            tool_name: 调用的工具名称。多工具聚合时传入逗号分隔的多个名称。
            tool_raw_output: 工具执行的原始输出文本。
            tool_latency_ms: 工具执行耗时（毫秒）。多工具时取全部工具耗时之和。
            tool_risk_level: 工具风险等级。多工具时取链中最高的等级。
            prompt_manager: Prompt Manager 实例。
        返回:
            IntentAlignmentResult: 对齐校准后的结果。
                                    LLM 调用失败时降级使用工具原始输出。
        """
        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_ALIGNMENT, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_ALIGNMENT,
            {
                "USER_INPUT": user_input,
                "INTENT_SUMMARY": intent_summary,
                "TOOL_NAME": tool_name,
                "TOOL_RAW_OUTPUT": tool_raw_output,
                "TOOL_LATENCY_MS": str(tool_latency_ms),
                "TOOL_RISK_LEVEL": tool_risk_level,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_ALIGNMENT, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=IntentAlignmentResult,
                    timeout=30.0,
                )

                logger.info(
                    f"MCP 意图对齐完成 trace_id={trace_id} "
                    f"tool_name={tool_name} "
                    f"quality_issue={response.quality_issue}"
                )
                return response

            except Exception as exc:
                logger.warning(
                    f"MCP 意图对齐 Agent 校准失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    # 重试耗尽，降级：直接使用工具原始输出
                    logger.warning(
                        f"MCP 意图对齐降级 trace_id={trace_id} "
                        f"使用工具原始输出"
                    )
                    return IntentAlignmentResult(
                        calibrated_output=tool_raw_output,
                        quality_issue=True,
                        quality_description="意图对齐 LLM 调用失败，降级使用工具原始输出",
                        data_source=f"{tool_name}（降级）",
                    )
