"""输入重构节点。"""

from __future__ import annotations

from typing import Any

from app.agent.input_reconstructor import InputReconstructorAgent
from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import (
    ChatStatusStage,
    ChatStatusState,
    DagRouteHint,
    IntentCategory,
    PrimaryIntent,
    RetrievalType,
)
from app.workflow.constants import (
    CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON,
    CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
    CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
    PROMPT_VARIABLE_CORE_SUMMARY,
    PROMPT_VARIABLE_KEY_FACTS,
    PROMPT_VARIABLE_MEMORY_SNIPPETS,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import format_recent_history


class InputReconstructionNode(ChatWorkflowNode):
    """用户输入重构节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.INPUT_RECONSTRUCTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        # 发布 RUNNING 状态
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.INPUT_RECONSTRUCTION,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.RUNNING),
        )

        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.INPUT_RECONSTRUCTION,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.COMPLETED),
                is_terminal=True,
            )
            return state
        try:
            memory_snippets = format_recent_history(state.session_state.recent_messages)
            state.session_state.memory_snippets = memory_snippets

            system_prompt = await prompt_manager.assemble_prompt(PromptCategory.INPUT_RECONSTRUCTION, {})

            memory_prompt = await prompt_manager.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION,
                {
                    PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
                    PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
                    PROMPT_VARIABLE_MEMORY_SNIPPETS: memory_snippets,
                },
            )

            primary_intents = [item.value for item in PrimaryIntent]
            categories = [item.value for item in IntentCategory]
            dag_route_hints = [item.value for item in DagRouteHint]
            retrieval_types = [item.value for item in RetrievalType]

            runtime_prompt = await prompt_manager.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION,
                {
                    "USER_INPUT": state.input_payload.raw_user_message,
                    "PRIMARY_INTENTS": '"' + '", "'.join(primary_intents) + '"',
                    "CATEGORIES": '"' + '", "'.join(categories) + '"',
                    "DAG_ROUTE_HINTS": '"' + '", "'.join(dag_route_hints) + '"',
                    "RETRIEVAL_TYPES": '"' + '", "'.join(retrieval_types) + '"',
                },
            )
            from app.llm.client import llm_client

            result = await InputReconstructorAgent(llm_client).process(
                trace_id=state.runtime.trace_id,
                user_input=state.input_payload.raw_user_message,
                system_prompt=system_prompt,
                memory_prompt=memory_prompt,
                runtime_prompt=runtime_prompt,
            )

            reconstruction = result.reconstruction
            retrieval_routing = result.retrieval_routing
            required_types = {item.value for item in result.intent_routing.required_retrieval_types}
            long_term = retrieval_routing.long_term_memory
            external = retrieval_routing.external_knowledge

            state.route_state.reconstructed_text = state.input_payload.raw_user_message
            state.route_state.disambiguated_text = (
                reconstruction.disambiguated_text or state.input_payload.raw_user_message
            )
            state.route_state.user_intent_summary = result.intent_routing.category.value

            state.route_state.should_enter_long_term_memory_rag = (
                RetrievalType.LONG_TERM_MEMORY.value in required_types and long_term.trigger
            )
            state.route_state.should_enter_knowledge_rag = (
                RetrievalType.EXTERNAL_KNOWLEDGE.value in required_types and external.trigger
            )

            state.route_state.search_queries = long_term.search_queries
            state.route_state.entity_mentions = long_term.entity_mentions
            state.route_state.temporal_focus = long_term.temporal_focus.model_dump(mode="json")

            state.route_state.external_search_queries = external.search_queries
            state.route_state.external_entity_mentions = external.entity_mentions
            state.route_state.external_temporal_focus = (
                external.temporal_focus.model_dump(mode="json") if external.temporal_focus else {}
            )

            state.route_state.knowledge_route = retrieval_routing.route_strategy
            state.route_state.route_reasons = [
                long_term.trigger_reason or CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
                external.trigger_reason or CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
            ]

            state.route_state.emotion_state = result.emotion_state.model_dump(mode="json")

            # --- Phase 12：MCP 工具调用判定 ---
            # 做什么：从输入重构结果中提取 MCP 工具调用判定。
            #         如果 result.mcp_tool_judgment 非空且 need_tool=True，则标记需要进入 MCP 节点，
            #         同时将 mcp_judgment JSON 存入路由状态以供下游使用。
            # 为什么这样做：工具调用判定作为输入重构的结构化输出，由 LLM 在一轮调用中完成，
            #             避免额外增加模型调用次数。
            has_tool_judgment = (
                result.mcp_tool_judgment is not None
                and result.mcp_tool_judgment.need_tool
            )
            state.route_state.should_enter_mcp_tool = has_tool_judgment
            state.route_state.mcp_judgment_json = (
                result.mcp_tool_judgment.model_dump(mode="json")
                if result.mcp_tool_judgment
                else None
            )

            # --- Phase 12（v3.0）：MCP Skill 调用判定（取代原有工具判定）---
            # 做什么：从输入重构结果中提取 MCP Skill 判定。
            #         如果 result.skill_judgment 非空且 need_skill=True，则标记需要进入 Skill 节点，
            #         同时将 skill_judgment JSON 存入路由状态以供下游 Agent 1 使用。
            # 为什么这样做：Skill 判定是工具判定的升级版，系统不再直接判定"是否使用工具"，
            #             而是判定"是否使用技能"，具体使用什么工具由 Skill 展开后决定。
            has_skill_judgment = (
                result.skill_judgment is not None
                and result.skill_judgment.need_skill
            )
            state.route_state.should_enter_skill = has_skill_judgment
            state.route_state.skill_judgment_json = (
                result.skill_judgment.model_dump(mode="json")
                if result.skill_judgment
                else None
            )

            # 发布 COMPLETED 状态
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.INPUT_RECONSTRUCTION,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

            return state
        except Exception as exc:
            logger.warning(
                f"输入重构节点降级 trace_id={state.runtime.trace_id} "
                f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} error={exc}"
            )
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)

            # 发布 ERROR 状态（前端可见，安抚用户）
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.INPUT_RECONSTRUCTION,
                status=ChatStatusState.ERROR,
                display_text=get_chat_status_text(ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.ERROR),
                is_terminal=True,
                error=str(exc),
            )

            return state

    def _apply_rule_fallback(self, state: ChatWorkflowState, reason: str) -> None:
        raw = state.input_payload.raw_user_message
        state.route_state.reconstructed_text = raw
        state.route_state.disambiguated_text = raw
        state.route_state.user_intent_summary = IntentCategory.CHAT.value
        memory_keywords = ("记得", "之前", "上次", "以前", "我说过")
        knowledge_keywords = ("文档", "资料", "知识库", "引用", "出处", "依据")
        state.route_state.should_enter_long_term_memory_rag = any(keyword in raw for keyword in memory_keywords)
        state.route_state.should_enter_knowledge_rag = any(keyword in raw for keyword in knowledge_keywords)
        state.route_state.search_queries = [raw] if state.route_state.should_enter_long_term_memory_rag else []
        state.route_state.external_search_queries = [raw] if state.route_state.should_enter_knowledge_rag else []
        state.route_state.route_reasons = [reason]
        state.route_state.emotion_state = {
            "primary_emotion": "NEUTRAL",
            "intensity": 0.0,
            "valence": 0.0,
            "arousal": 0.0,
            "emotion_trigger": reason,
        }

        # Phase 12: MCP 工具调用降级关键字检测
        mcp_keywords = ("时间", "几点", "日期", "天气", "温度", "查询", "搜索")
        state.route_state.should_enter_mcp_tool = any(
            keyword in raw for keyword in mcp_keywords
        )
        if state.route_state.should_enter_mcp_tool:
            state.route_state.mcp_judgment_json = {
                "need_tool": True,
                "reason": f"降级规则触发：输入中包含 MCP 关键字",
                "keywords": [raw],
            }
        else:
            state.route_state.mcp_judgment_json = None

        # Phase 12（v3.0）: Skill 调用降级关键字检测
        skill_keywords = ("查询", "搜索", "分析", "计算", "处理", "生成", "翻译")
        state.route_state.should_enter_skill = any(
            keyword in raw for keyword in skill_keywords
        )
        if state.route_state.should_enter_skill:
            state.route_state.skill_judgment_json = {
                "need_skill": True,
                "reason": f"降级规则触发：输入中包含 Skill 关键字",
                "keywords": [raw],
            }
        else:
            state.route_state.skill_judgment_json = None

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
