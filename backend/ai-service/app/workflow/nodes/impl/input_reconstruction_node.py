"""输入重构节点。"""

from __future__ import annotations

from datetime import datetime
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
    RagDocumentStatus,
    RagRetrievalRoute,
    RetrievalType,
)
from app.workflow.constants import (
    CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON,
    CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
    CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
    PROMPT_VARIABLE_KNOWLEDGE_DOCS,
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

    async def _load_knowledge_docs_text(self) -> str:
        """
        从 PostgreSQL 查询当前用户知识库中所有 ACTIVE 状态的文档，格式化为 LLM 可读的文本块。

        做什么：调用 rag_pg_repo.list_documents() 获取文档列表，
               并按如下格式拼装：
               --
               [文档1] doc_name
               [简介1] doc_desc
               --
               [文档2] doc_name
               [简介2] doc_desc
               --

        为什么这样做：让 InputReconstructor Agent 在解析用户输入时能够感知当前知识库中有哪些文档，
                     从而更准确地判断是否需要触发知识库检索。

        边界条件：rag_pg_repo 为 None 时返回空字符串；
                 文档 description 为空时仅输出文档名称。
        """
        rag_pg_repo = self.dependencies.rag_pg_repo
        if not rag_pg_repo:
            return ""

        try:
            # 只查询 ACTIVE 状态的文档，确保 LLM 只感知到已完成摄入的有效文档。
            documents = await rag_pg_repo.list_documents(limit=200, status=RagDocumentStatus.ACTIVE.value)
        except Exception as e:
            logger.warning(f"加载知识库文档列表失败 error={e}")
            return ""

        if not documents:
            return ""

        lines: list[str] = []
        for idx, doc in enumerate(documents, start=1):
            lines.append("--")
            lines.append(f"[文档{idx}] {doc.filename or '未命名文档'}")
            if doc.description:
                lines.append(f"[简介{idx}] {doc.description}")
        if lines:
            lines.append("--")

        logger.info(f"加载知识库文档列表完成 count={len(documents)} lines={len(lines)}")
        return "\n".join(lines)

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

            # 在 Python 层将枚举列表预转为逗号分隔的字符串，避免在 Jinja2 模板中使用 | join filter。
            # 为什么这样做：Jinja2 的 finalize 函数与 | join filter 在特定环境下存在交互不稳定问题，
            # 可能导致 finalize 将 list 转为 JSON 字符串后 join 无法正常处理，最终 render_template
            # 抛异常并降级返回原始模板文本（包含未渲染的 {{ PRIMARY_INTENTS | join(', ') }}）。
            # 改为在 Python 层预 join，模板只接收纯字符串变量，彻底消除 filter pipeline 不稳定性。
            primary_intents = ", ".join(item.value for item in PrimaryIntent)
            categories = ", ".join(item.value for item in IntentCategory)
            dag_route_hints = ", ".join(item.value for item in DagRouteHint)
            retrieval_types = ", ".join(item.value for item in RetrievalType)
            route_strategies = ", ".join(item.value for item in RagRetrievalRoute)

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
            from app.llm.client import llm_client

            # 加载知识库文档列表，注入到 KNOWLEDGE_DOCS 变量
            knowledge_docs_text = await self._load_knowledge_docs_text()

            # 效仿 MCP Intent Judge 的变量注入方式：使用 assemble_prompt() 一次性渲染完整 Prompt。
            # 为什么这样做：render_prompt() 返回的三槽位内容需要由 Agent 内部手动拼接，
            # 且枚举约束（PRIMARY_INTENTS 等）已通过 {{ VAR_NAME }} 变量注入到 runtime.j2 模板中，
            # 不再需要硬编码的 enum_constraints。assemble_prompt() 直接从 PG active 版本
            # 用 Jinja2 渲染所有变量，确保模板变量被正确替换，消除了两阶段拼接的不一致性。
            full_prompt = await prompt_manager.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION,
                {
                    "CORE_SUMMARY": state.session_state.short_summary,
                    "KEY_FACTS": "\n".join(state.session_state.key_facts) if state.session_state.key_facts else "",
                    "MEMORY_SNIPPETS": memory_snippets,
                    PROMPT_VARIABLE_KNOWLEDGE_DOCS: knowledge_docs_text,
                    "CURRENT_TIME": current_time,
                    "USER_INPUT": state.input_payload.raw_user_message,
                    "PRIMARY_INTENTS": primary_intents,
                    "CATEGORIES": categories,
                    "DAG_ROUTE_HINTS": dag_route_hints,
                    "RETRIEVAL_TYPES": retrieval_types,
                    "ROUTE_STRATEGIES": route_strategies,
                },
            )

            logger.info(
                f"组装 Input Reconstruction Prompt trace_id={state.runtime.trace_id}, "
                f"full_prompt={full_prompt}"
            )

            result = await InputReconstructorAgent(llm_client).process(
                trace_id=state.runtime.trace_id,
                user_input=state.input_payload.raw_user_message,
                prompt=full_prompt,
            )

            logger.info(
                f"Input Reconstruction trace_id={state.runtime.trace_id}, "
                f"result={result.model_dump(mode='json')}"
            )

            reconstruction = result.reconstruction
            retrieval_routing = result.retrieval_routing
            required_types = {item.value for item in result.intent_routing.required_retrieval_types}
            long_term = retrieval_routing.long_term_memory
            external = retrieval_routing.external_knowledge

            state.route_state.reconstructed_text = (
                reconstruction.disambiguated_text or state.input_payload.raw_user_message
            )
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

            # v3.0 变更：MCP 判断已从输入重构节点剥离，延迟到 MCP_INTENT_JUDGE 节点处理。
            # 因此此处不再读取 mcp_tool_judgment 和 skill_judgment 字段。

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

        # v3.0 变更：MCP 判断已从输入重构节点剥离，延迟到 MCP_INTENT_JUDGE 节点处理。
        # 因此此处不再设置 should_enter_mcp_tool / should_enter_skill 相关字段。
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
