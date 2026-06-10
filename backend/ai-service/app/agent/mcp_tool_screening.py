"""
MCP 工具初筛 Agent（Agent 1）。

做什么：接收输入重构节点的 JSON 判定结果，通过混合检索召回候选工具，
        由 LLM 依据轻量元数据（不含 Schema）输出有序工具链（ToolChainPlan）。
        支持单工具和多工具链式调用规划。
为什么这样做：将工具筛选与参数提取分离，Agent 1 的 Memory Prompt 仅注入
            轻量元数据，避免将庞大的 parameters_schema 灌入初筛阶段，
            大幅节省 Token 消耗。
边界条件：
    - 混合检索返回空列表时直接标记 no_suitable_tool=True，不调用 LLM。
    - LLM 输出的 tool_chain 中任一工具不在候选列表中时降级为 no_suitable_tool=True。
    - LLM 调用失败重试 2 次，重试耗尽后降级返回空工具链。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import ToolChainPlan
from app.prompt.types import PromptCategory


class MCPToolScreeningAgent:
    """MCP 工具初筛 Agent。

    做什么：根据用户输入和输入重构判定结果，从工具池中召回候选工具，
            由 LLM 评估后输出有序工具链（ToolChainPlan）。
    为什么这样做：将工具筛选作为独立 Agent，实现职责分离。
                 Agent 1 只关注"选什么工具"，不关心"怎么调工具"。
    """

    def __init__(self) -> None:
        """
        初始化工具初筛 Agent。

        做什么：设置最大重试次数和默认 Top-K 数量。
        为什么这样做：max_retries=2 确保 LLM 调用有有限容错，
                     top_k=5 保证候选工具数量适中。
        """
        self.max_retries = 2
        self.top_k = 5

    @property
    def model_name(self) -> str:
        """
        获取当前配置的中模型名称。

        做什么：从全局配置容器中读取 MEDIUM 模型的 model_id。
        为什么这样做：Agent 1 使用中模型作为折中方案，
                     既不使用昂贵的大模型，也不用能力不足的小模型。
        返回:
            str: 模型 ID，如 "gpt-4o-mini"。配置不存在时返回默认值。
        """
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def screen(
        self,
        trace_id: str,
        user_input: str,
        mcp_judgment: dict[str, Any],
        prompt_manager: Any,
        inference_service: Any | None = None,
    ) -> ToolChainPlan:
        """
        执行工具初筛，输出有序工具链。

        做什么：1. 从 mcp_judgment 中提取 keywords 作为查询文本。
                2. 通过 MCPToolRegistry.hybrid_search_tools() 检索候选工具。
                3. 组装三槽位 Prompt（system + memory + runtime）。
                4. 调用 LLM 的 generate_structured() 输出 ToolChainPlan。
                5. 校验 LLM 输出的工具名称是否在候选列表中。
        参数:
            trace_id: 全链路追踪 ID。
            user_input: 用户原始输入。
            mcp_judgment: 输入重构节点的 JSON 判定结果，
                          包含 need_tool、reason、keywords 字段。
            prompt_manager: Prompt Manager 实例，用于组装 Prompt。
            inference_service: 推理服务实例，可选，用于向量检索增强。
        返回:
            ToolChainPlan: 有序工具链计划。
                           无候选工具或 LLM 初筛失败时返回空链。
        """
        registry = MCPToolRegistry()

        # 从 mcp_judgment 中提取 keywords，如果没有则直接用用户输入
        keywords = mcp_judgment.get("keywords", [user_input])
        if isinstance(keywords, list):
            query = " ".join(keywords)
        else:
            query = str(keywords)

        # 混合检索候选工具
        candidates = await registry.hybrid_search_tools(
            query=query,
            top_k=self.top_k,
            inference_service=inference_service,
        )

        # 无候选工具时直接标记不匹配
        if not candidates:
            logger.info(
                f"MCP 工具初筛无候选工具 trace_id={trace_id} "
                f"query={query}"
            )
            return ToolChainPlan(
                tool_chain=[],
                reasoning="混合检索未召回任何候选工具",
                no_suitable_tool=True,
            )

        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_SCREENING, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_SCREENING,
            {
                "CANDIDATE_TOOLS": candidates,
                "USER_INPUT": user_input,
                "MCP_NEED_TOOL": mcp_judgment.get("need_tool", False),
                "MCP_REASON": mcp_judgment.get("reason", ""),
                "MCP_KEYWORDS": ", ".join(keywords) if isinstance(keywords, list) else str(keywords),
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_TOOL_SCREENING, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=ToolChainPlan,
                    timeout=30.0,
                )

                # 校验所有工具是否在候选列表中
                if not response.no_suitable_tool and response.tool_chain:
                    candidate_names = {c["name"] for c in candidates}
                    for step in response.tool_chain:
                        if step.tool_name not in candidate_names:
                            logger.warning(
                                f"MCP 工具初筛 Agent 选定工具 '{step.tool_name}' "
                                f"不在候选列表中 trace_id={trace_id}，降级"
                            )
                            return ToolChainPlan(
                                tool_chain=[],
                                reasoning=f"LLM 选定 '{step.tool_name}' 不在候选列表中",
                                no_suitable_tool=True,
                            )

                logger.info(
                    f"MCP 工具初筛完成 trace_id={trace_id} "
                    f"tool_chain={[s.tool_name for s in response.tool_chain]} "
                    f"no_suitable_tool={response.no_suitable_tool}"
                )
                return response

            except Exception as exc:
                logger.warning(
                    f"MCP 工具初筛 Agent 决策失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    # 重试耗尽，降级返回空工具链
                    return ToolChainPlan(
                        tool_chain=[],
                        reasoning="LLM 初筛调用失败，降级为无工具",
                        no_suitable_tool=True,
                    )
