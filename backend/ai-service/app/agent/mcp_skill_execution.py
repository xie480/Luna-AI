"""
MCP Skill 执行 Agent（Agent 3）。

做什么：按照 Agent 2 输出的 ExecutionPlan 逐项执行工具。
        每步执行前，将当前步骤的资源配置、资源上下文和前序工具结果
        注入到 LLM Prompt，由 LLM 判断是否可以继续执行（can_proceed）
        并提取工具调用参数（tool_parameters）。
        执行后累积结果供退回检测使用。
为什么这样做：将"是否可以继续"的判断和"工具参数提取"交由 LLM 一次调用完成，
            业务代码负责统计和状态追踪。
边界条件：
    - execution_plan 为空时不执行任何操作。
    - 工具执行失败时记录错误但不中断整个计划。
    - 每步执行结果累积到 tool_results 数组。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.skill_types import ExecutionPlan
from app.prompt.types import PromptCategory


class MCPSkillExecutionAgent:
    """MCP Skill 执行 Agent（按执行计划执行工具）。"""

    def __init__(self) -> None:
        """初始化 Skill 执行 Agent。"""
        pass

    @property
    def model_name(self) -> str:
        """获取当前配置的中模型名称。"""
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def execute_step(
        self,
        trace_id: str,
        step_name: str,
        execution_plan: ExecutionPlan,
        tool_results: list[dict[str, Any]],
        resource_context: dict[str, str],
        prompt_manager: Any,
        user_input: str,
    ) -> dict[str, Any]:
        """执行单个工具步骤。

        做什么：将当前步骤的所需资源、已加载资源上下文、前序工具结果
                注入到 LLM Prompt 中，由 LLM 判断是否可以继续执行，
                并在可以继续时提取工具调用参数。

        参数:
            trace_id: 全链路追踪 ID。
            step_name: 执行步骤名称（工具名称）。
            execution_plan: 执行计划。
            tool_results: 已累积的工具执行结果。
            resource_context: 资源上下文映射（resource_name -> extracted_info）。
            prompt_manager: Prompt Manager 实例。
            user_input: 用户原始输入。
        返回:
            dict: 包含 tool_name、success、can_proceed、tool_parameters、
                  fallback_reason、latency_ms。
                  can_proceed: 由 LLM 判断，业务代码仅做透传。
                  tool_parameters: LLM 提取的工具调用参数（can_proceed=true 时）。
        """
        import json
        import time
        from app.llm.client import llm_client

        started_at = time.monotonic()

        # 查找执行计划中当前 state
        current_state = None
        current_state_key = None
        for state_key, state_val in execution_plan.states.items():
            if step_name in state_val.tools:
                current_state = state_val
                current_state_key = state_key
                break

        if current_state is None:
            return {
                "tool_name": step_name,
                "success": False,
                "can_proceed": False,
                "tool_parameters": {},
                "fallback_reason": f"执行计划中未找到工具 '{step_name}' 所属的 state",
                "latency_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            }

        # 构建当前步骤的上下文
        required_resources = current_state.resource
        depends_on_tools: list[str] = []

        # 从 execution_plan 中推断前序依赖（当前 state 之前的 state 中的 tools）
        if current_state_key and execution_plan.execution_order:
            current_idx = execution_plan.execution_order.index(current_state_key)
            for prev_key in execution_plan.execution_order[:current_idx]:
                prev_state = execution_plan.states.get(prev_key)
                if prev_state:
                    depends_on_tools.extend(prev_state.tools)

        # 注入资源上下文
        full_context: dict[str, str] = {}
        for res_name in required_resources:
            if res_name in resource_context:
                full_context[res_name] = resource_context[res_name]

        # 前序工具结果
        previous_tool_results: list[dict[str, Any]] = [
            r for r in tool_results
            if r.get("tool_name") in depends_on_tools
        ]

        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_EXECUTION, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_EXECUTION,
            {
                "STEP_NAME": step_name,
                "STEP_PURPOSE": f"工具 '{step_name}' 的调用目的（来自执行计划）",
                "REQUIRED_RESOURCES": json.dumps(required_resources, ensure_ascii=False),
                "DEPENDS_ON_TOOLS": json.dumps(depends_on_tools, ensure_ascii=False),
                "RESOURCE_CONTEXT": full_context,
                "PREVIOUS_TOOL_RESULTS": previous_tool_results,
                "USER_INPUT": user_input,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_EXECUTION, {}
        )

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        try:
            response = await llm_client.generate_structured(
                model=self.model_name,
                messages=[{"role": "system", "content": full_prompt}],
                response_format={
                    "type": "json_object",
                    "properties": {
                        "can_proceed": {"type": "boolean"},
                        "tool_parameters": {"type": "object"},
                        "fallback_reason": {"type": "string"},
                    },
                },
                timeout=30.0,
            )

            can_proceed = response.get("can_proceed", False)
            tool_parameters = response.get("tool_parameters", {})
            fallback_reason = response.get("fallback_reason", "")

            elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))

            logger.info(
                f"MCP Skill 执行 Agent 完成 trace_id={trace_id} "
                f"tool_name={step_name} "
                f"can_proceed={can_proceed} "
                f"latency_ms={elapsed_ms}"
            )

            return {
                "tool_name": step_name,
                "success": can_proceed,
                "can_proceed": can_proceed,
                "tool_parameters": tool_parameters,
                "fallback_reason": fallback_reason,
                "resource_context_injected": list(full_context.keys()),
                "latency_ms": elapsed_ms,
            }

        except Exception as exc:
            logger.warning(
                f"MCP Skill 执行 Agent LLM 调用失败 trace_id={trace_id} "
                f"tool_name={step_name} error={exc!s}"
            )
            return {
                "tool_name": step_name,
                "success": False,
                "can_proceed": False,
                "tool_parameters": {},
                "fallback_reason": f"LLM 执行判断失败: {exc!s}",
                "resource_context_injected": [],
                "latency_ms": max(0, int((time.monotonic() - started_at) * 1000)),
            }
