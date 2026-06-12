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

from typing import Any

from app.logger import logger
from app.prompt.types import PromptCategory


class MCPIntentJudgeJudgment:
    """MCP 前置判断结果。

    做什么：封装 MCP 前置判断 Agent 的输出。
    """
    def __init__(
        self,
        need_skill: bool,
        reason: str,
        keywords: list[str],
        mcp_intent: str,
    ):
        self.need_skill = need_skill
        self.reason = reason
        self.keywords = keywords
        self.mcp_intent = mcp_intent

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "need_skill": self.need_skill,
            "reason": self.reason,
            "keywords": self.keywords,
            "mcp_intent": self.mcp_intent,
        }


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

        # 组装三槽位 Prompt
        system_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_JUDGE, {}
        )
        memory_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_JUDGE,
            {
                "RECONSTRUCTED_INPUT": reconstructed_input,
                "RAG_EVIDENCE": rag_evidence or "（无 RAG 召回证据）",
            },
        )
        runtime_prompt = await prompt_manager.assemble_prompt(
            PromptCategory.MCP_INTENT_JUDGE, {}
        )

        from app.llm.client import llm_client

        full_prompt = f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

        # 带重试的 LLM 调用
        for attempt in range(self.max_retries + 1):
            try:
                # 记录完整 prompt 日志
                logger.info(
                    f"[MCP Intent Judge] 完整 Prompt trace_id={trace_id} "
                    f"attempt={attempt} full_prompt={full_prompt}"
                )

                response = await llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format={
                        "type": "json_object",
                        "properties": {
                            "need_skill": {"type": "boolean"},
                            "reason": {"type": "string"},
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "mcp_intent": {"type": "string"},
                        },
                    },
                    timeout=30.0,
                )

                # 记录 LLM 完整输出
                logger.info(
                    f"[MCP Intent Judge] LLM 完整输出 trace_id={trace_id} "
                    f"attempt={attempt} output={response}"
                )

                need_skill = response.get("need_skill", False)
                reason = response.get("reason", "")
                keywords = response.get("keywords", [reconstructed_input])
                mcp_intent = response.get("mcp_intent", "")

                if not isinstance(keywords, list):
                    keywords = [str(keywords)]

                logger.info(
                    f"MCP 前置判断完成 trace_id={trace_id} "
                    f"need_skill={need_skill} reason={reason}"
                )

                return MCPIntentJudgeJudgment(
                    need_skill=need_skill,
                    reason=reason,
                    keywords=keywords,
                    mcp_intent=mcp_intent,
                )

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
