"""
MCP 前置判断 Agent — 延迟 MCP 意图判定。

做什么：接收输入重构节点的输出（重构后文本、RAG 召回证据、用户意图），
         由 LLM 判断是否需要使用 MCP 能力（Skill / Tool）。
         如果需要，输出 MCP 意图文本（mcp_intent）和判定结果。
为什么这样做：将 MCP 判断从输入重构节点中剥离，延迟到 MCP 前置节点处理。
             这样输入重构节点聚焦于基本的语义理解，而 MCP 判断可以根据
             更多上下文（如 RAG 召回证据）做出更准确的决策。
边界条件：
    - 输入重构失败降级时，使用规则匹配判断。
    - LLM 调用失败重试 2 次，重试耗尽后使用规则匹配兜底。
    - need_skill=False 时，mcp_intent 为空字符串。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.logger import logger
from app.prompt.types import PromptCategory


from pydantic import BaseModel, Field

class MCPIntentJudgeJudgment(BaseModel):
    """MCP 前置判断结果。

    做什么：封装 MCP 前置判断 Agent 的输出。
    """
    need_skill: bool = Field(..., description="布尔值。true 表示需要使用 MCP 能力；false 表示无需使用。")
    reason: str = Field(..., description="判断原因说明，详细解释为什么需要或不需要 MCP 能力。")
    keywords: list[str] = Field(..., description="关键词数组，用于匹配技能。至少包含 1 个，建议 1~5 个关键词。当 need_skill=false 时为空数组 []。")
    mcp_intent: str = Field(..., description="MCP 意图文本。当 need_skill=true 时，为重构后的需求描述；当 need_skill=false 时，此字段为空字符串。")
    check: str = Field(
        default="",
        description="系统校验推演过程，包含需求分析、判断准确性、意图提炼等维度的自检结果。",
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return self.model_dump(mode="json")


class MCPIntentJudgeAgent:
    """MCP 前置判断 Agent。

    做什么：在 MCP 节点执行前，根据重构后的用户输入和 RAG 召回证据，
            判断是否需要使用 MCP 能力。
    """

    def __init__(self) -> None:
        """初始化 MCP 前置判断 Agent。"""
        self.max_retries = 2

    @property
    def model_name(self) -> str:
        """获取当前配置的中模型名称。"""
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def judge(
        self,
        trace_id: str,
        reconstructed_input: str,
        rag_evidence: str,
        prompt_manager: Any,
    ) -> MCPIntentJudgeJudgment:
        """执行 MCP 前置判断。

        参数:
            trace_id: 全链路追踪 ID。
            reconstructed_input: 重构后的用户输入文本。
            rag_evidence: RAG 召回证据文本（如果有）。
            prompt_manager: Prompt Manager 实例。
        返回:
            MCPIntentJudgeJudgment: 判断结果。
        """

        # 组装完整的 Prompt
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        full_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_JUDGE,
            {
                "CURRENT_TIME": current_time,
                "RECONSTRUCTED_INPUT": reconstructed_input,
                "RAG_EVIDENCE": rag_evidence or "（无 RAG 召回证据）",
            },
        )

        from app.llm.client import llm_client

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                # 记录完整 prompt 日志
                logger.info(
                    f"[MCP Intent Judge] 完整 Prompt trace_id={trace_id} "
                    f"attempt={attempt} full_prompt={full_prompt}"
                )

                from app.agent.mcp_intent_judge import MCPIntentJudgeJudgment
                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format=MCPIntentJudgeJudgment,
                    timeout=30.0,
                )

                # 记录 LLM 完整输出
                logger.info(
                    f"[MCP Intent Judge] LLM 完整输出 trace_id={trace_id} "
                    f"attempt={attempt} output={response}"
                )

                logger.info(
                    f"MCP 前置判断完成 trace_id={trace_id} "
                    f"need_skill={response.need_skill} reason={response.reason}"
                )

                return response

            except Exception as exc:
                logger.warning(
                    f"MCP 前置判断 Agent 决策失败 trace_id={trace_id} "
                    f"attempt={attempt} error={exc!s}"
                )
                if attempt == self.max_retries:
                    # 重试耗尽，使用规则匹配兜底
                    return self._rule_fallback(reconstructed_input)

    def _rule_fallback(self, user_input: str) -> MCPIntentJudgeJudgment:
        """规则匹配兜底。

        做什么：当 LLM 调用失败时，使用关键字规则粗略判断是否需要 MCP。
        """
        skill_keywords = ("查询", "搜索", "分析", "计算", "处理", "生成", "翻译",
                         "查找", "统计", "汇总", "比较", "转换")
        need_skill = any(keyword in user_input for keyword in skill_keywords)

        if need_skill:
            return MCPIntentJudgeJudgment(
                need_skill=True,
                reason="降级规则触发：输入中包含 Skill 关键字",
                keywords=[user_input],
                mcp_intent=user_input,
            )
        else:
            return MCPIntentJudgeJudgment(
                need_skill=False,
                reason="规则兜底：未检测到 Skill 关键字",
                keywords=[],
                mcp_intent="",
            )
