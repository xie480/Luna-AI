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

from datetime import datetime
from typing import Any

from app.config.settings import settings
from app.logger import logger
from app.mcp.skill_registry import SkillRegistry
from app.mcp.skill_types import ExecutionPlan
from app.prompt.types import PromptCategory


# 最大执行步长（从 .env 配置读取）
_MAX_EXECUTION_STEPS: int = settings.skill_max_execution_steps


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
        mcp_intent: str,
        prompt_manager: Any,
    ) -> ExecutionPlan:
        """执行多 Skill 加载，输出组合执行计划。

        遍历所有选中的 Skill，聚合其 tools 和 resources，
        由 LLM 跨 Skill 选拔后生成统一的执行计划。

        参数:
            trace_id: 全链路追踪 ID。
            skill_ids: Agent 1 选中的 Skill ID 列表（按优先级排序）。
            mcp_intent: 重构后的 MCP 意图文本（用于替代原始用户输入注入 Prompt）。
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

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        full_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_LOADING,
            {
                "CURRENT_TIME": current_time,
                "SKILL_CONTEXT": skills_context,
                "AGGREGATED_TOOLS": tools_context,
                "AGGREGATED_RESOURCES": resources_context,
                "MCP_INTENT": mcp_intent,
                "MAX_STEPS": str(_MAX_EXECUTION_STEPS),
            },
        )

        from app.llm.client import llm_client

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                # 记录完整 prompt 日志
                logger.info(
                    f"[MCP Skill Loading] 完整 Prompt trace_id={trace_id} "
                    f"attempt={attempt} full_prompt={full_prompt}"
                )

                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=ExecutionPlan,
                    timeout=30.0,
                )

                # 记录 LLM 完整输出
                logger.info(
                    f"[MCP Skill Loading] LLM 完整输出 trace_id={trace_id} "
                    f"attempt={attempt} output={response.model_dump(mode='json')}"
                )

                # 校验所有 state 中的工具名称是否在聚合列表中
                valid_tool_names = {t["name"] for t in aggregated_tools}
                valid_resource_names = {r["name"] for r in aggregated_resources}

                for state_key, state_val in response.states.items():
                    # v3.0：校验单工具字段 tool（字符串）
                    if state_val.tool and state_val.tool not in valid_tool_names:
                        logger.warning(
                            f"MCP Skill 加载 Agent state '{state_key}' 中选定工具 "
                            f"'{state_val.tool}' 不在聚合工具列表中 trace_id={trace_id}，"
                            f"修正为空计划"
                        )
                        return ExecutionPlan(
                            states={},
                            reasoning=f"LLM 选定工具 '{state_val.tool}' 不在聚合工具列表中",
                        )
                    # v3.0：校验单资源字段 resource（字符串）
                    if state_val.resource and state_val.resource not in valid_resource_names:
                        logger.warning(
                            f"MCP Skill 加载 Agent state '{state_key}' 中选定资源 "
                            f"'{state_val.resource}' 不在聚合资源列表中 trace_id={trace_id}，"
                            f"修正为空计划"
                        )
                        return ExecutionPlan(
                            states={},
                            reasoning=f"LLM 选定资源 '{state_val.resource}' 不在聚合资源列表中",
                        )

                # v3.0：校验 state 数量不超过最大步长
                if len(response.states) > _MAX_EXECUTION_STEPS:
                    logger.warning(
                        f"MCP Skill 加载 Agent state 数量 {len(response.states)} "
                        f"超过最大步长 {_MAX_EXECUTION_STEPS} trace_id={trace_id}，修正为空计划"
                    )
                    return ExecutionPlan(
                        states={},
                        reasoning=f"LLM 生成 {len(response.states)} 个 state，超过最大步长 {_MAX_EXECUTION_STEPS}",
                    )

                logger.info(
                    f"MCP Skill 加载完成 trace_id={trace_id} "
                    f"skills={skill_ids} "
                    f"aggregated_tools={len(aggregated_tools)} "
                    f"aggregated_resources={len(aggregated_resources)} "
                    f"states={list(response.states.keys())} "
                    f"total_steps={len(response.states)}"
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
                        reasoning=f"LLM 加载调用失败: {exc!s}",
                    )
