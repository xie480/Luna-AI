"""
MCP Skill 加载 Agent（Agent 2），支持多 Skill 组合加载。

做什么：接收 Agent 1 选中的一个或多个 Skill ID，遍历获取每个 Skill 的
        完整展开信息，将所有 tools 和 resources 聚合后由 LLM 跨 Skill
        选拔最终需要的组合，生成统一的执行计划（ExecutionPlan）。
为什么这样做：Agent 1 可能选择多个 Skill 协作完成任务，Agent 2 需要
            将多 Skill 的 tools/resources 合并后让 LLM 统一选拔，
            避免各 Skill 单独规划导致的冲突或冗余。
边界条件：
    - skill_ids 列表为空时直接返回空计划，触发退回机制。
    - 所有选中的 Skill 都不存在时返回空计划。
    - LLM 调用失败重试 2 次，重试耗尽后返回空计划。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.skill_registry import SkillRegistry
from app.mcp.skill_types import ExecutionPlan
from app.prompt.types import PromptCategory


class MCPSkillLoadingAgent:
    """MCP Skill 加载 Agent（支持多 Skill 组合加载）。"""

    def __init__(self) -> None:
        """初始化 Skill 加载 Agent。"""
        self.max_retries = 2

    @property
    def model_name(self) -> str:
        """获取当前配置的中模型名称。"""
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def load(
        self,
        trace_id: str,
        skill_ids: list[str],
        user_input: str,
        prompt_manager: Any,
    ) -> ExecutionPlan:
        """执行多 Skill 加载，输出组合执行计划。

        遍历所有选中的 Skill，聚合其 tools 和 resources，
        由 LLM 跨 Skill 选拔后生成统一的执行计划。

        参数:
            trace_id: 全链路追踪 ID。
            skill_ids: Agent 1 选中的 Skill ID 列表（按优先级排序）。
            user_input: 用户原始输入。
            prompt_manager: Prompt Manager 实例。
        返回:
            ExecutionPlan: 组合执行计划。无有效 Skill 时返回空计划。
        """
        registry = SkillRegistry()

        # 遍历所有选中的 Skill，收集 tools 和 resources
        aggregated_tools: list[dict[str, Any]] = []
        aggregated_resources: list[dict[str, Any]] = []
        skill_details: list[tuple[str, str, str]] = []
        seen_tool_names: set[str] = set()
        seen_resource_uris: set[str] = set()

        for sid in skill_ids:
            detail = registry.get_skill_detail(sid)
            if detail is None:
                logger.warning(
                    f"MCP Skill 加载 Agent 技能不存在 trace_id={trace_id} "
                    f"skill_id={sid}，跳过"
                )
                continue

            skill_details.append((sid, detail.name, detail.description))

            # 聚合 tools（去重）
            for tool in detail.tools:
                name = tool.get("name", "")
                if name not in seen_tool_names:
                    seen_tool_names.add(name)
                    # 标记来源 Skill
                    tool = {**tool, "from_skill": detail.name}
                    aggregated_tools.append(tool)

            # 聚合 resources（按 URI 去重）
            for res in detail.resources:
                uri = res.get("uri", "")
                if uri and uri not in seen_resource_uris:
                    seen_resource_uris.add(uri)
                    res = {**res, "from_skill": detail.name}
                    aggregated_resources.append(res)

        # 无有效 Skill 时降级
        if not skill_details:
            combined_reason = "; ".join(
                f"Skill '{sid}' 不存在" for sid in skill_ids
            )
            return ExecutionPlan(
                states={},
                execution_order=[],
                total_expected_steps=0,
                reasoning=combined_reason,
            )

        # 构建多 Skill 上下文描述
        skills_context = "\n".join(
            f"  - 技能名称：「{name}」技能描述：{desc}"
            for _, name, desc in skill_details
        )

        # 标记每个工具/资源的来源 Skill
        tools_context = "\n".join(
            f"  - 工具名称：「{t['name']}」来源技能：{t.get('from_skill', 'unknown')} "
            f"简介：{t.get('description', '')} 核心用途：{t.get('core_purpose', '')}"
            for t in aggregated_tools
        ) if aggregated_tools else "  （无可用工具）"

        resources_context = "\n".join(
            f"  - 资源名称：「{r['name']}」来源技能：{r.get('from_skill', 'unknown')} "
            f"类型：{r.get('resource_type', 'file')} 描述：{r.get('description', '')}"
            for r in aggregated_resources
        ) if aggregated_resources else "  （无可用资源）"

        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_LOADING, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_LOADING,
            {
                "SKILL_CONTEXT": skills_context,
                "AGGREGATED_TOOLS": tools_context,
                "AGGREGATED_RESOURCES": resources_context,
                "USER_INPUT": user_input,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_LOADING, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=ExecutionPlan,
                    timeout=30.0,
                )

                # 校验所有 state 中的工具名称是否在聚合列表中
                valid_tool_names = {t["name"] for t in aggregated_tools}
                valid_resource_names = {r["name"] for r in aggregated_resources}

                for state_key, state_val in response.states.items():
                    for tool_name in state_val.tools:
                        if tool_name not in valid_tool_names:
                            logger.warning(
                                f"MCP Skill 加载 Agent state '{state_key}' 中选定工具 "
                                f"'{tool_name}' 不在聚合工具列表中 trace_id={trace_id}，"
                                f"修正为空计划"
                            )
                            return ExecutionPlan(
                                states={},
                                execution_order=[],
                                total_expected_steps=0,
                                reasoning=f"LLM 选定工具 '{tool_name}' 不在聚合工具列表中",
                            )
                    for res_name in state_val.resource:
                        if res_name not in valid_resource_names:
                            logger.warning(
                                f"MCP Skill 加载 Agent state '{state_key}' 中选定资源 "
                                f"'{res_name}' 不在聚合资源列表中 trace_id={trace_id}，"
                                f"修正为空计划"
                            )
                            return ExecutionPlan(
                                states={},
                                execution_order=[],
                                total_expected_steps=0,
                                reasoning=f"LLM 选定资源 '{res_name}' 不在聚合资源列表中",
                            )

                # 校验 execution_order 中的 state_key 是否在 states 中
                for state_key in response.execution_order:
                    if state_key not in response.states:
                        logger.warning(
                            f"MCP Skill 加载 Agent execution_order 中的 "
                            f"'{state_key}' 不在 states 中 trace_id={trace_id}，"
                            f"修正为空计划"
                        )
                        return ExecutionPlan(
                            states={},
                            execution_order=[],
                            total_expected_steps=0,
                            reasoning=f"执行顺序中的 state_key '{state_key}' 不在 states 中",
                        )

                logger.info(
                    f"MCP Skill 加载完成 trace_id={trace_id} "
                    f"skills={skill_ids} "
                    f"aggregated_tools={len(aggregated_tools)} "
                    f"aggregated_resources={len(aggregated_resources)} "
                    f"states={list(response.states.keys())} "
                    f"expected_steps={response.total_expected_steps}"
                )
                return response

            except Exception as exc:
                logger.warning(
                    f"MCP Skill 加载 Agent 决策失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    return ExecutionPlan(
                        states={},
                        execution_order=[],
                        total_expected_steps=0,
                        reasoning=f"LLM 加载调用失败: {exc!s}",
                    )
