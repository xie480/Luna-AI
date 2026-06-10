"""
MCP Tool Calling 专属 Agent（Agent 2，循环执行模式）。

做什么：接收工具链中当前步骤的工具名称和可选的上一轮工具执行结果，
        提取该工具的完整 Schema 注入 Memory Prompt，由 LLM 精确提取调用参数。
        第 2+ 轮会额外将前序工具结果格式化为 Previous tool result 注入 System Prompt。
为什么这样做：将参数提取与工具筛选分离，Agent 2 只关注参数精确度。
            链式调用时前序结果自动注入上下文，确保工具间数据传递。
边界条件：
    - 工具不存在于注册中心时直接标记 call_parameters_failed=True。
    - LLM 调用失败重试 2 次，重试耗尽后标记失败。
    - 第 1 轮 previous_tool_result 为空字符串，不注入前序结果。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import ToolCallingResult
from app.prompt.types import PromptCategory


class MCPToolCallingAgent:
    """MCP Tool Calling 专属 Agent（循环执行模式）。

    做什么：根据当前工具名称和上下文提取工具调用参数。
    为什么这样做：将参数提取作为独立阶段，精确控制 Schema 注入位置。
    """

    def __init__(self) -> None:
        """
        初始化 Tool Calling Agent。

        做什么：设置最大重试次数。
        为什么这样做：max_retries=2 确保 LLM 调用有有限容错。
        """
        self.max_retries = 2

    @property
    def model_name(self) -> str:
        """
        获取当前配置的中模型名称。

        做什么：从全局配置容器中读取 MEDIUM 模型的 model_id。
        为什么这样做：Agent 2 使用中模型作为参数提取模型，
                     在精度和成本之间取得平衡。
        返回:
            str: 模型 ID，如 "gpt-4o-mini"。配置不存在时返回默认值。
        """
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def extract_parameters(
        self,
        trace_id: str,
        tool_name: str,
        user_input: str,
        memory_snippets: str,
        core_summary: str,
        key_facts: list[str],
        prompt_manager: Any,
        previous_tool_result: str = "",
    ) -> ToolCallingResult:
        """
        提取当前工具调用参数（支持链式调用）。

        做什么：1. 从注册中心获取工具的完整 Schema。
                2. 组装三槽位 Prompt（system + memory + runtime）。
                3. 第 2+ 轮将前序结果追加到 System Prompt 末尾。
                4. 调用 LLM 的 generate_structured() 输出 ToolCallingResult。
        参数:
            trace_id: 全链路追踪 ID。
            tool_name: 当前要调用的工具名称。
            user_input: 用户原始输入。
            memory_snippets: 近期对话片段。
            core_summary: 核心摘要。
            key_facts: 关键事实列表。
            prompt_manager: Prompt Manager 实例。
            previous_tool_result: 前序工具的执行结果文本。第 1 轮为空字符串，
                                  第 2+ 轮由上层节点注入。
        返回:
            ToolCallingResult: 当前工具的参数提取结果。
                               工具不存在或 LLM 调用失败时标记失败。
        """
        import json

        registry = MCPToolRegistry()
        full_schema = registry.get_tool_full_schema(tool_name)

        # 工具不存在时直接返回失败
        if full_schema is None:
            logger.warning(
                f"MCP Tool Calling Agent 工具不存在 trace_id={trace_id} "
                f"tool_name={tool_name}"
            )
            return ToolCallingResult(
                parameters={},
                parameter_explanation="",
                call_parameters_failed=True,
                failure_reason=f"工具 '{tool_name}' 不存在或未注册",
            )

        # 组装 System Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_CALLING, {}
        )

        # 第 2+ 轮：前序结果追加到 System Prompt 末尾
        if previous_tool_result:
            system_prompt += (
                f"\n\n<strong>【前序工具执行结果】</strong>\n"
                f"Previous tool result: {previous_tool_result}"
            )

        # 组装 Memory Prompt（注入完整 Schema）
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_CALLING,
            {
                "TOOL_NAME": tool_name,
                "TOOL_DESCRIPTION": full_schema["description"],
                "TOOL_PARAMETERS_SCHEMA": json.dumps(
                    full_schema["parameters_schema"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "USER_INPUT": user_input,
                "MEMORY_SNIPPETS": memory_snippets,
                "CORE_SUMMARY": core_summary,
                "KEY_FACTS": "\n".join(key_facts),
                "PREVIOUS_TOOL_RESULT": previous_tool_result,
            },
        )

        # 组装 Runtime Prompt
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_CALLING, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=ToolCallingResult,
                    timeout=30.0,
                )

                logger.info(
                    f"MCP Tool Calling 完成 trace_id={trace_id} "
                    f"tool_name={tool_name} "
                    f"has_previous_result={'是' if previous_tool_result else '否'} "
                    f"call_parameters_failed={response.call_parameters_failed}"
                )
                return response

            except Exception as exc:
                logger.warning(
                    f"MCP Tool Calling Agent 参数提取失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    # 重试耗尽，返回失败
                    return ToolCallingResult(
                        parameters={},
                        parameter_explanation="",
                        call_parameters_failed=True,
                        failure_reason=f"LLM 参数提取失败: {exc!s}",
                    )
