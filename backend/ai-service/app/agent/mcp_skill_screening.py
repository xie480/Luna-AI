"""
MCP Skill 初筛 Agent（Agent 1）。

做什么：接收 MCP 前置判断节点的结果，获取候选 Skill 元数据，
         由 LLM 依据轻量元数据（不含 Tool/Resource）输出 SkillChainPlan。
         此时 Skill 处于未展开状态，仅作为能力指针存在。
为什么这样做：将原有的"工具初筛"升级为"技能初筛"。Skill 作为能力
             指针，Agent 1 在初筛阶段不加载具体工具和资源，
             大幅节省 Token 消耗。
边界条件：
    - 候选 Skill 列表为空时直接标记 no_suitable_skill=True，不调用 LLM。
    - LLM 输出的 skill_id 不在候选列表中时降级为 no_suitable_skill=True。
    - LLM 调用失败重试 2 次，重试耗尽后降级返回空列表。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.skill_registry import SkillRegistry
from app.mcp.skill_types import SkillChainPlan
from app.prompt.types import PromptCategory


class MCPSkillScreeningAgent:
    """MCP Skill 初筛 Agent。"""

    def __init__(self) -> None:
        """初始化 Skill 初筛 Agent。"""
        self.max_retries = 2

    @property
    def model_name(self) -> str:
        """获取当前配置的中模型名称。"""
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def screen(
        self,
        trace_id: str,
        mcp_intent: str,
        skill_judgment: dict[str, Any],
        prompt_manager: Any,
    ) -> SkillChainPlan:
        """执行 Skill 初筛，输出选中的 Skill ID 列表。

        参数:
            trace_id: 全链路追踪 ID。
            mcp_intent: 重构后的 MCP 意图文本（用于替代原始用户输入注入 Prompt）。
            skill_judgment: MCP 前置判断节点的判定 JSON，
                             包含 need_skill、reason、keywords 字段。
            prompt_manager: Prompt Manager 实例。
        返回:
            SkillChainPlan: Skill 初筛结果。
        """
        registry = SkillRegistry()
        keywords = skill_judgment.get("keywords", [mcp_intent])
        if not isinstance(keywords, list):
            keywords = [str(keywords)]

        # 获取候选 Skill 元数据（未展开状态）
        candidates = registry.list_skill_metadata()

        # 无候选 Skill 时直接标记
        if not candidates:
            logger.info(f"MCP Skill 初筛无候选技能 trace_id={trace_id}")
            return SkillChainPlan(
                selected_skill_ids=[],
                reasoning="无可用技能",
                no_suitable_skill=True,
            )

        # 提取退回上下文（如果存在）
        fallback_context = skill_judgment.get("fallback_context", {})
        execution_snapshot = fallback_context.get("execution_snapshot", {})
        fallback_count = fallback_context.get("fallback_count", 0)

        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_SCREENING, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_SCREENING,
            {
                "CANDIDATE_SKILLS": candidates,
                "MCP_INTENT": mcp_intent,
                "SKILL_NEED_TOOL": skill_judgment.get("need_skill", False),
                "SKILL_REASON": skill_judgment.get("reason", ""),
                "SKILL_KEYWORDS": ", ".join(keywords),
                "FALLBACK_CONTEXT": execution_snapshot if execution_snapshot else "",
                "FALLBACK_COUNT": fallback_count,
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_SKILL_SCREENING, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                # 记录完整 prompt 日志
                logger.info(
                    f"[MCP Skill Screening] 完整 Prompt trace_id={trace_id} "
                    f"attempt={attempt} full_prompt={full_prompt}"
                )

                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=SkillChainPlan,
                    timeout=30.0,
                )

                # 记录 LLM 完整输出
                logger.info(
                    f"[MCP Skill Screening] LLM 完整输出 trace_id={trace_id} "
                    f"attempt={attempt} output={response.model_dump(mode='json')}"
                )

                # 校验所有 skill_id 是否在候选列表中
                if not response.no_suitable_skill and response.selected_skill_ids:
                    candidate_ids = {c["skill_id"] for c in candidates}
                    for sid in response.selected_skill_ids:
                        if sid not in candidate_ids:
                            logger.warning(
                                f"MCP Skill 初筛 Agent 选定 skill_id '{sid}' "
                                f"不在候选列表中 trace_id={trace_id}，降级"
                            )
                            return SkillChainPlan(
                                selected_skill_ids=[],
                                reasoning=f"LLM 选定 '{sid}' 不在候选列表中",
                                no_suitable_skill=True,
                            )

                logger.info(
                    f"MCP Skill 初筛完成 trace_id={trace_id} "
                    f"selected_skills={response.selected_skill_ids} "
                    f"no_suitable_skill={response.no_suitable_skill}"
                )
                return response

            except Exception as exc:
                logger.warning(
                    f"MCP Skill 初筛 Agent 决策失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    return SkillChainPlan(
                        selected_skill_ids=[],
                        reasoning="LLM 初筛调用失败，降级为无技能",
                        no_suitable_skill=True,
                    )
