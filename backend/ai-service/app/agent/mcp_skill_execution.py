"""
MCP Skill 执行 Agent（Agent 3）。

做什么：按照 Agent 2 输出的 ExecutionPlan 逐项执行工具。
         每步执行前，将当前步骤的 goal（执行目标）、资源配置、资源上下文和前序工具结果
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

import json
import time
from datetime import datetime
from typing import Any

from app.llm.client import llm_client
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
        step_goal: str,
        execution_plan: ExecutionPlan,
        tool_results: list[dict[str, Any]],
        resource_context: dict[str, str],
        prompt_manager: Any,
        mcp_intent: str,
        skill_memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行单个工具步骤。

        做什么：将当前步骤的 goal、所需资源、已加载资源上下文、前序工具结果
                注入到 LLM Prompt 中，由 LLM 判断是否可以继续执行，
                并在可以继续时提取工具调用参数。

        参数:
            trace_id: 全链路追踪 ID。
            step_name: 执行步骤名称（工具名称）。
            step_goal: 当前步骤的执行目标（来自 ExecutionPlan 中的 goal 字段）。
            execution_plan: 执行计划。
            tool_results: 已累积的工具执行结果。
            resource_context: 资源上下文映射（resource_name -> extracted_info）。
            prompt_manager: Prompt Manager 实例。
            mcp_intent: 重构后的 MCP 意图文本（用于替代原始用户输入注入 Prompt）。
        返回:
            dict: 包含 tool_name、success、can_proceed、tool_parameters、
                  fallback_reason、latency_ms。
                  can_proceed: 由 LLM 判断，业务代码仅做透传。
                  tool_parameters: LLM 提取的工具调用参数（can_proceed=true 时）。
        """
        started_at = time.monotonic()

        # 查找执行计划中当前 state
        current_state = None
        current_state_key = None
        for state_key, state_val in execution_plan.states.items():
            if step_name == state_val.tool:
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
        required_resources = [current_state.resource] if current_state.resource else []

        # 推断前序依赖：当前 state_key 之前的 state 中的工具
        depends_on_tools: list[str] = []
        state_keys = sorted(execution_plan.states.keys())
        if current_state_key and state_keys:
            current_idx = state_keys.index(current_state_key)
            for prev_key in state_keys[:current_idx]:
                prev_state = execution_plan.states.get(prev_key)
                if prev_state and prev_state.tool:
                    depends_on_tools.append(prev_state.tool)

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

        # 组装通用状态的 memory prompt（使用框架层的 memory.j2）
        # 注意：MCP Skill 执行 Agent 的 Prompt 装配方式有别于其他 Agent。
        # 其他 Agent 使用 assemble_prompt 将 PG 中 system/memory/runtime 三槽位拼接为完整 Prompt。
        # 而 Skill 执行 Agent 的 Prompt 需要特殊装配：
        #   1. 从 skill 定义的 execution 阶段 content_path 加载工具专属 Prompt 文件（Jinja2 模板），
        #      该模板已包含完整的角色定义、系统指令和输出格式约束。
        #   2. 只从 PG 的 mcp_skill_execution 分类中提取 memory 槽位（包含当前步骤上下文、
        #      所需资源、已加载资源内容、前序工具执行结果、MCP 意图等运行时信息）。
        #   3. 将 memory 槽位内容注入到工具专属 Prompt 的 {{ system_context }} 变量中。
        # 为什么这样做：工具专属 Prompt 已经包含了完整的系统指令和输出格式约束，
        #             不需要再注入 PG 中 mcp_skill_execution 的 system/runtime 槽位内容。
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")

        # 使用 render_prompt 仅获取 memory 槽位的渲染内容
        # 为什么这样做：render_prompt 按三槽位分别渲染后返回 PromptPayload，
        #             调用方可以只取 memory 槽位内容注入到工具 Prompt 的 {{ system_context }}。
        #             而 assemble_prompt 将三槽位拼接为一个字符串，无法分离 memory 槽位内容。
        try:
            prompt_payload = await prompt_manager.render_prompt(
                PromptCategory.MCP_SKILL_EXECUTION,
                {
                    "CURRENT_TIME": current_time,
                    "STEP_TOOL": step_name,
                    "STEP_GOAL": step_goal,
                    "REQUIRED_RESOURCES": json.dumps(required_resources, ensure_ascii=False),
                    "DEPENDS_ON_TOOLS": json.dumps(depends_on_tools, ensure_ascii=False),
                    "RESOURCE_CONTEXT": full_context,
                    "PREVIOUS_TOOL_RESULTS": previous_tool_results,
                    "MCP_INTENT": mcp_intent,
                },
            )
            system_context_str = prompt_payload.memory  # 仅使用 memory 槽位
        except Exception:
            # 降级：如果 render_prompt 失败（如缓存管理器不可用），回退到 assemble_prompt
            # 保持与之前一致的行为，避免因 prompt 渲染失败导致整个执行步骤中断。
            logger.warning(
                f"render_prompt 失败，降级使用 assemble_prompt "
                f"trace_id={trace_id} step_name={step_name}"
            )
            system_context_str = await prompt_manager.assemble_prompt(
                PromptCategory.MCP_SKILL_EXECUTION,
                {
                    "CURRENT_TIME": current_time,
                    "STEP_TOOL": step_name,
                    "STEP_GOAL": step_goal,
                    "REQUIRED_RESOURCES": json.dumps(required_resources, ensure_ascii=False),
                    "DEPENDS_ON_TOOLS": json.dumps(depends_on_tools, ensure_ascii=False),
                    "RESOURCE_CONTEXT": full_context,
                    "PREVIOUS_TOOL_RESULTS": previous_tool_results,
                    "MCP_INTENT": mcp_intent,
                },
            )

        skill_name = current_state.skill if current_state else ""
        full_prompt = ""

        # 尝试加载该工具的专属 Prompt（优先从 prompts 表根据 skill_id + tool_id 查询）
        if skill_name:
            from app.prompt.types import render_template
            from app.mcp.skill_registry import SkillRegistry
            import os

            # 通过 SkillRegistry 查找 tool_id
            registry = SkillRegistry()
            tool_id = ""
            detail = None
            for sid, det in registry._skills.items():
                if det.name == skill_name:
                    detail = det
                    for t in det.tools:
                        if t.get("name") == step_name:
                            logger.debug(f"找到工具 {step_name} 对应的 Skill {skill_name}")
                            tool_id = t.get("tool_id", "")
                            break
                    break

            # 只要有 detail（Skill 定义），就从 skill 定义的 execution 阶段 content_path 加载工具专属 Prompt
            if detail is not None:
                logger.debug(f"正在加载工具 {step_name} 的专属 Prompt，tool_id={tool_id}")
                # 从 skill 定义的 prompts 中获取 execution 阶段的 Prompt 定义。
                # prompts 数据结构：{phase: {tool_id_or_empty: {content_path, variables}}}
                # 查找优先级：先按 tool_id 查找工具专属 prompt，未找到则降级到空字符串 key（skill 级通用 prompt）。
                exec_prompts_by_tool = detail.prompts.get("execution", {})
                if not isinstance(exec_prompts_by_tool, dict):
                    exec_prompts_by_tool = {}
                # 优先查找工具专属 prompt
                exec_prompt_def = exec_prompts_by_tool.get(tool_id, {})
                # 如果没找到工具专属的，降级到 skill 级通用 prompt
                if not exec_prompt_def:
                    exec_prompt_def = exec_prompts_by_tool.get("", {})
                content_path = exec_prompt_def.get("content_path", "") if isinstance(exec_prompt_def, dict) else ""

                tool_template = ""
                if content_path:
                    # 基于项目根目录解析 content_path 加载工具专属 Prompt 文件
                    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    full_path = os.path.join(base_dir, content_path)
                    if os.path.exists(full_path):
                        with open(full_path, encoding="utf-8") as f:
                            tool_template = f.read()
                            logger.info(f"从 content_path 加载工具专属 Prompt 成功: content_path={content_path}")
                    else:
                        logger.warning(f"从 content_path 加载工具专属 Prompt 失败: content_path={content_path}")
                if tool_template:
                    # 合并变量：将通用上下文（由 memory.j2 渲染得到）注入到 system_context 字段
                    # search_tool_prompt.j2 中通过 {{ system_context }} 接收 memory.j2 的渲染内容
                    merged_context: dict[str, Any] = {
                        "system_context": system_context_str,
                        "user_input": mcp_intent,
                    }
                    # 如果传入了专属的 skill_memory_context（如动态提取的多轮搜索上下文变量），也一并注入
                    if skill_memory_context is not None:
                        merged_context.update(skill_memory_context)

                    full_prompt = render_template(tool_template, merged_context)

        # 如果没有渲染出专属 Prompt，则回退到通用步骤上下文 Prompt。
        # 修复：system_context_str 已通过 memory.j2 模板一次性注入所有步骤变量（CURRENT_TIME / STEP_TOOL / STEP_GOAL
        # / REQUIRED_RESOURCES / DEPENDS_ON_TOOLS / RESOURCE_CONTEXT / PREVIOUS_TOOL_RESULTS / MCP_INTENT），
        # 内容完整。之前错误地额外调用两次 assemble_prompt（仅传入 CURRENT_TIME）并与 system_context_str 拼接，
        # 导致 memory.j2 被渲染三次注入到最终 prompt 中，造成内容重复且部分变量缺失。
        if not full_prompt:
            logger.debug(f"正在加载通用步骤上下文 Prompt")
            full_prompt = system_context_str

        # 记录完整 prompt 日志
        logger.info(
            f"[MCP Skill Execution] 完整 Prompt trace_id={trace_id} "
            f"step_name={step_name} full_prompt={full_prompt}"
        )

        try:
            response_schema = {
                "type": "json_object",
                "properties": {
                    "can_proceed": {"type": "boolean"},
                    "tool_parameters": {"type": "object"},
                    "fallback_reason": {"type": "string"},
                },
                "required": ["can_proceed", "tool_parameters", "fallback_reason"]
            }
            
            schema_prompt = (
                f"\n\n你必须以 JSON 格式回复，严格遵循以下 JSON Schema 定义：\n"
                f"{json.dumps(response_schema, ensure_ascii=False, indent=2)}\n\n"
                "请确保输出的 JSON 完全符合上述 Schema，不要包含任何额外说明文字。"
            )
            
            response_text = await llm_client.generate_structured_text(
                model=self.model_name,
                messages=[{"role": "system", "content": full_prompt + schema_prompt}],
                timeout=30.0,
            )

            # 清理可能存在的 markdown 代码块
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            result_dict = json.loads(cleaned_text)

            # 记录 LLM 完整输出
            logger.info(
                f"[MCP Skill Execution] LLM 完整输出 trace_id={trace_id} "
                f"step_name={step_name} output={result_dict}"
            )

            can_proceed = result_dict.get("can_proceed", False)
            tool_parameters = result_dict.get("tool_parameters", {})
            fallback_reason = result_dict.get("fallback_reason", "")

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
