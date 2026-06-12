"""
MCP 前置判断节点 — 延迟 MCP 意图判断。

做什么：作为 LangGraph 的节点适配器，在知识 RAG 检索完成后，
        根据重构后的用户输入和 RAG 召回证据，由 LLM 判断是否需要使用 MCP 能力。
为什么这样做：将 MCP 判断从输入重构节点中剥离，让 MCP 前置判断能利用
             更多上下文（包括 RAG 召回证据），做出更准确的决策。
边界条件：
    - prompt_manager 不可用时降级为规则匹配。
    - RAG 未触发（旁路）时，evidence 文本为空字符串。
    - 所有异常由本节点捕获并降级，不阻断主工作流。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.mcp_intent_judge import MCPIntentJudgeAgent
from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import (
    CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import first_reason


class MCPIntentJudgeNode(ChatWorkflowNode):
    """MCP 前置判断节点。

    做什么：在知识 RAG 之后、MCP Skill 节点之前执行，
            根据上下文判断是否需要使用 MCP 能力。
    """

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.MCP_INTENT_JUDGE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        # 发布 RUNNING 状态
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.MCP_INTENT_JUDGE,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.MCP_INTENT_JUDGE, ChatStatusState.RUNNING
            ),
        )

        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            return self._rule_fallback(state, "Prompt 管理器不可用")

        try:
            # 收集 MCP 判断所需上下文
            reconstructed_input = state.route_state.reconstructed_text or state.input_payload.raw_user_message

            # 收集 RAG 召回证据文本
            rag_evidence = ""
            if state.knowledge_state.evidences:
                evidence_parts = []
                for ev in state.knowledge_state.evidences:
                    if hasattr(ev, 'content') and ev.content:
                        evidence_parts.append(ev.content[:500])
                rag_evidence = "\n---\n".join(evidence_parts)
            if not rag_evidence and state.memory_state.prompt_memory_text:
                rag_evidence = state.memory_state.prompt_memory_text

            # 执行 MCP 前置判断
            judge_agent = MCPIntentJudgeAgent()
            judgment = await judge_agent.judge(
                trace_id=state.runtime.trace_id,
                reconstructed_input=reconstructed_input,
                rag_evidence=rag_evidence,
                prompt_manager=prompt_manager,
            )

            # 将判断结果写入路由状态
            state.route_state.should_enter_skill = judgment.need_skill
            state.route_state.mcp_intent = judgment.mcp_intent
            state.route_state.skill_judgment_json = judgment.to_dict()
            state.route_state.route_reasons.append(
                judgment.reason or CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON
            )

            # 发布 COMPLETED 状态
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.MCP_INTENT_JUDGE,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.MCP_INTENT_JUDGE, ChatStatusState.COMPLETED
                ),
                is_terminal=True,
            )

            return state

        except Exception as exc:
            logger.warning(
                f"MCP 前置判断节点异常降级 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc!s}"
            )
            return self._rule_fallback(state, f"MCP 前置判断异常: {exc!s}")

    def _rule_fallback(self, state: ChatWorkflowState, reason: str) -> ChatWorkflowState:
        """规则匹配降级。
        
        做什么：当 LLM 调用失败时，使用关键字规则判断是否需要 MCP。
        """
        raw = state.input_payload.raw_user_message
        skill_keywords = ("查询", "搜索", "分析", "计算", "处理", "生成", "翻译",
                         "查找", "统计", "汇总", "比较", "转换")
        need_skill = any(keyword in raw for keyword in skill_keywords)

        state.route_state.should_enter_skill = need_skill
        state.route_state.mcp_intent = raw if need_skill else ""
        state.route_state.skill_judgment_json = {
            "need_skill": need_skill,
            "reason": f"降级规则触发：{reason}",
            "keywords": [raw] if need_skill else [],
            "mcp_intent": raw if need_skill else "",
        }
        state.route_state.route_reasons.append(f"规则降级: {reason}")

        # 发布 SKIPPED 状态（不可见）
        try:
            publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
            if publisher:
                asyncio.create_task(
                    publisher.publish(
                        trace_id=state.runtime.trace_id,
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        stage=ChatStatusStage.MCP_INTENT_JUDGE,
                        state=ChatStatusState.SKIPPED,
                        display_text="",
                        is_visible=False,
                        is_terminal=True,
                    )
                )
        except Exception:
            pass

        return state

    async def _publish_chat_status(
        self,
        state: ChatWorkflowState,
        stage: ChatStatusStage,
        status: ChatStatusState,
        display_text: str,
        is_visible: bool = True,
        is_terminal: bool = False,
        error: str = "",
    ) -> None:
        """发布 Chat 状态事件。"""
        publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
        if publisher is None:
            return
        await publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=stage,
            state=status,
            display_text=display_text,
            is_visible=is_visible,
            is_terminal=is_terminal,
            error=error,
        )
