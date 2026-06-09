"""
Phase 8.5 Chat Workflow 节点适配器实现。

做什么：把既有输入重构、Redis 会话、长期记忆、用户画像、知识库 RAG、上下文治理、Prompt、LLM、持久化与后处理能力收拢为节点。
为什么这样做：LangGraph 只负责编排，不吞并现有服务；节点适配器负责统一输入输出、异常处理、观测字段和状态写回。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

from app.agent.input_reconstructor import InputReconstructorAgent
from app.context.compression_governor import MemorySlotCompressionGovernor
from app.llm.context_manager import count_tokens
from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.rag.retrieval import RagRetrievalOrchestrator
from app.rag.types import RagSearchRequest
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, Interaction
from app.repository.models import InteractionModel
from app.types.constants import (
    DagRouteHint,
    IntentCategory,
    PrimaryIntent,
    RetrievalType,
    Role,
)
from app.user_profile.service import UserProfileService
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_STREAM_EMPTY_RESPONSE_ERROR,
    CHAT_STREAM_GENERATION_ERROR,
    CHAT_STREAM_TYPE_EMOTION_UPDATE,
    CHAT_STREAM_TYPE_REPLY_CHUNK,
    CHAT_STREAM_TYPE_THOUGHT_CONTENT,
    CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED,
    CHAT_WORKFLOW_CONTEXT_WINDOW_READY,
    CHAT_WORKFLOW_EMPTY_PROFILE_REASON,
    CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON,
    CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
    CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
    CHAT_WORKFLOW_PG_WRITE_FAILED,
    CHAT_WORKFLOW_PG_WRITE_OK,
    CHAT_WORKFLOW_PG_WRITE_SKIPPED,
    CHAT_WORKFLOW_POSTPROCESS_SUCCESS_REASON,
    CHAT_WORKFLOW_REDIS_WRITE_FAILED,
    CHAT_WORKFLOW_REDIS_WRITE_OK,
    CHAT_WORKFLOW_REDIS_WRITE_SKIPPED,
    PROMPT_VARIABLE_CORE_SUMMARY,
    PROMPT_VARIABLE_CURRENT_MESSAGE,
    PROMPT_VARIABLE_CURRENT_TIME,
    PROMPT_VARIABLE_EMOTION_AROUSAL,
    PROMPT_VARIABLE_EMOTION_INTENSITY,
    PROMPT_VARIABLE_EMOTION_PRIMARY,
    PROMPT_VARIABLE_EMOTION_TRIGGER,
    PROMPT_VARIABLE_EMOTION_VALENCE,
    PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE,
    PROMPT_VARIABLE_KEY_FACTS,
    PROMPT_VARIABLE_LONG_TERM_MEMORY,
    PROMPT_VARIABLE_MEMORY_SNIPPETS,
    PROMPT_VARIABLE_USER_PROFILE,
    ChatWorkflowErrorCode,
    ChatWorkflowNodeType,
)
from app.workflow.context import (
    ChatErrorState,
    ChatWorkflowState,
    KnowledgeCitation,
    MemoryMutationCandidate,
    ModelMessage,
    PostprocessError,
)
from app.workflow.events import ChatStreamChunkPayload, ChatWorkflowEventPublisher
from app.workflow.nodes.base import ChatWorkflowNode


class WorkflowDependencies:
    """Chat Workflow 节点依赖容器。"""

    def __init__(
        self,
        *,
        redis_repo: ChatHistoryRedisRepo | None,
        pg_repo: ChatHistoryPGRepo | None,
        prompt_manager: PromptManager | None,
        memory_manager: MemoryManager | None,
        rag_orchestrator: RagRetrievalOrchestrator | None,
        user_profile_service: UserProfileService | None,
        event_publisher: ChatWorkflowEventPublisher | None,
    ):
        """保存节点运行依赖，依赖由 FastAPI lifespan 注入。"""
        self.redis_repo = redis_repo
        self.pg_repo = pg_repo
        self.prompt_manager = prompt_manager
        self.memory_manager = memory_manager
        self.rag_orchestrator = rag_orchestrator
        self.user_profile_service = user_profile_service
        self.event_publisher = event_publisher


class InputReconstructionNode(ChatWorkflowNode):
    """用户输入重构节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.INPUT_RECONSTRUCTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行输入重构并产出条件路由字段。"""
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)
            return state

        try:
            memory_snippets = _format_recent_history(state.session_state.recent_messages)
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
            state.route_state.disambiguated_text = reconstruction.disambiguated_text or state.input_payload.raw_user_message
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
            return state
        except Exception as exc:
            logger.warning(
                f"输入重构节点降级 trace_id={state.runtime.trace_id} interaction_id={state.runtime.interaction_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)
            return state

    def _apply_rule_fallback(self, state: ChatWorkflowState, reason: str) -> None:
        """使用原始输入和保守规则生成路由，避免输入重构失败阻断闲聊。"""
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


class SessionContextLoadNode(ChatWorkflowNode):
    """会话窗口装载节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.SESSION_CONTEXT_LOAD,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        if not self.dependencies.redis_repo:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            state.session_state.token_budget_total = 0
            return state
        try:
            summary, history = await self.dependencies.redis_repo.get_context(state.runtime.session_id)
            state.session_state.recent_messages = history
            state.session_state.short_summary = summary.core_summary
            state.session_state.key_facts = _split_key_facts(summary.key_facts)
            state.session_state.memory_snippets = _format_recent_history(history)
            state.session_state.token_budget_used = count_tokens(state.session_state.memory_snippets)
            state.session_state.token_budget_total = max(state.session_state.token_budget_used, 0)
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_READY
        except Exception as exc:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            logger.warning(
                f"Redis 会话窗口装载失败，已降级为空窗口 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
        return state


class LongTermMemoryNode(ChatWorkflowNode):
    """长期记忆 RAG 条件节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.memory_state.entered_by_condition = True
        state.memory_state.condition_reason = _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON)
        if not self.dependencies.memory_manager:
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = "长期记忆管理器不可用"
            return state
        try:
            temporal_focus = state.route_state.temporal_focus
            text = await self.dependencies.memory_manager.retrieve_and_format_memories(
                query_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                query_vector=[],
                search_queries=state.route_state.search_queries,
                reference_time=temporal_focus.get("reference_time"),
                temporal_deviation=int(temporal_focus.get("temporal_deviation") or 0),
                entity_mentions=state.route_state.entity_mentions,
            )
            state.memory_state.prompt_memory_text = text
        except Exception as exc:
            state.memory_state.degraded = True
            state.memory_state.degraded_reason = f"长期记忆检索失败: {exc}"
            logger.warning(
                f"长期记忆 RAG 降级 trace_id={state.runtime.trace_id} session_id={state.runtime.session_id} error={exc}"
            )
        return state


class UserProfileInjectionNode(ChatWorkflowNode):
    """用户画像注入必须节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.USER_PROFILE_INJECTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.profile_state.injection_executed = True
        if not self.dependencies.user_profile_service:
            state.profile_state.prompt_profile_text = ""
            return state
        try:
            state.profile_state.prompt_profile_text = await self.dependencies.user_profile_service.get_prompt_summary(
                state.runtime.user_id
            )
            if not state.profile_state.prompt_profile_text:
                state.profile_state.degraded_reason = CHAT_WORKFLOW_EMPTY_PROFILE_REASON
        except Exception as exc:
            state.profile_state.degraded = True
            state.profile_state.degraded_reason = f"用户画像注入失败: {exc}"
            state.profile_state.prompt_profile_text = ""
            logger.warning(
                f"用户画像注入降级 trace_id={state.runtime.trace_id} session_id={state.runtime.session_id} error={exc}"
            )
        return state


class KnowledgeRagNode(ChatWorkflowNode):
    """知识库 RAG 条件节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.KNOWLEDGE_RAG,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.knowledge_state.entered_by_condition = True
        state.knowledge_state.condition_reason = _first_reason(state.route_state.route_reasons, CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON)
        state.knowledge_state.retrieval_route = state.route_state.knowledge_route.value
        if not self.dependencies.rag_orchestrator:
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = "知识库检索编排器不可用"
            return state
        try:
            request = RagSearchRequest(
                query=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                route=state.route_state.knowledge_route,
                retrieval_top_k=20,
                rerank_top_k=3,
                max_retries=3,
                disambiguated_text=state.route_state.disambiguated_text,
                search_queries=state.route_state.external_search_queries,
                temporal_focus=state.route_state.external_temporal_focus or None,
                entity_mentions=state.route_state.external_entity_mentions,
            )
            response = await self.dependencies.rag_orchestrator.search(request, state.runtime.trace_id)
            state.knowledge_state.evidences = response.evidences
            state.knowledge_state.prompt_knowledge_text = response.prompt_context
            state.knowledge_state.citations = [KnowledgeCitation(**item) for item in response.citations]
            state.generation_state.citations = state.knowledge_state.citations
        except Exception as exc:
            state.knowledge_state.degraded = True
            state.knowledge_state.degraded_reason = f"知识库检索失败: {exc}"
            logger.warning(
                f"知识库 RAG 降级 trace_id={state.runtime.trace_id} session_id={state.runtime.session_id} error={exc}"
            )
        return state


class ContextGovernanceNode(ChatWorkflowNode):
    """上下文治理节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.CONTEXT_GOVERNANCE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        emotion_state = state.route_state.emotion_state
        variables = {
            PROMPT_VARIABLE_CURRENT_TIME: current_time,
            PROMPT_VARIABLE_CURRENT_MESSAGE: state.input_payload.raw_user_message,
            PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
            PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
            PROMPT_VARIABLE_MEMORY_SNIPPETS: state.session_state.memory_snippets,
            PROMPT_VARIABLE_LONG_TERM_MEMORY: state.memory_state.prompt_memory_text,
            PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE: state.knowledge_state.prompt_knowledge_text,
            PROMPT_VARIABLE_USER_PROFILE: state.profile_state.prompt_profile_text,
            PROMPT_VARIABLE_EMOTION_PRIMARY: str(emotion_state.get("primary_emotion", "")),
            PROMPT_VARIABLE_EMOTION_INTENSITY: f"{float(emotion_state.get('intensity', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_VALENCE: f"{float(emotion_state.get('valence', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_AROUSAL: f"{float(emotion_state.get('arousal', 0.0)):.2f}",
            PROMPT_VARIABLE_EMOTION_TRIGGER: str(emotion_state.get("emotion_trigger", "")),
        }
        try:
            result = await MemorySlotCompressionGovernor().govern(
                trace_id=state.runtime.trace_id,
                session_id=state.runtime.session_id,
                message_id=state.input_payload.frontend_message_id,
                prompt_variables=variables,
            )
            state.prompt_state.prompt_variables = result.updated_variables
        except Exception as exc:
            logger.warning(
                f"上下文治理降级使用原始变量 trace_id={state.runtime.trace_id} session_id={state.runtime.session_id} error={exc}"
            )
            state.prompt_state.prompt_variables = variables
        return state


class PromptAssemblyNode(ChatWorkflowNode):
    """Prompt 装配节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.PROMPT_ASSEMBLY,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        if not self.dependencies.prompt_manager:
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message="PromptManager 不可用，无法装配主 Chat Prompt",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message)
        try:
            system_prompt = await self.dependencies.prompt_manager.assemble_prompt(
                PromptCategory.CHAT,
                state.prompt_state.prompt_variables,
            )
            state.prompt_state.system_prompt_text = system_prompt
            state.prompt_state.memory_slot_text = state.prompt_state.prompt_variables.get(PROMPT_VARIABLE_LONG_TERM_MEMORY, "")
            state.prompt_state.profile_slot_text = state.prompt_state.prompt_variables.get(PROMPT_VARIABLE_USER_PROFILE, "")
            state.prompt_state.knowledge_slot_text = state.prompt_state.prompt_variables.get(PROMPT_VARIABLE_EXTERNAL_KNOWLEDGE, "")
            state.prompt_state.final_messages = [
                ModelMessage(role=Role.SYSTEM.value, content=system_prompt),
                ModelMessage(role=Role.USER.value, content=state.input_payload.raw_user_message),
            ]
            state.prompt_state.final_prompt_tokens = count_tokens(system_prompt) + count_tokens(state.input_payload.raw_user_message)
            return state
        except Exception as exc:
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.PROMPT_ASSEMBLY_FAILED.value,
                message=f"Prompt 装配失败: {exc}",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message) from exc


class MainChatLlmNode(ChatWorkflowNode):
    """主 Chat LLM 流式生成节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.MAIN_CHAT_LLM,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        from app.llm.client import llm_client
        from app.llm.stream_parser import StreamParser

        started = time.time()
        first_chunk = True
        parser = StreamParser(state.runtime.trace_id)
        history_dicts = _history_to_model_messages(state.session_state.recent_messages)
        state.generation_state.model_name = llm_client.model_name
        state.generation_state.provider_name = getattr(llm_client, "base_url", "")
        state.generation_state.stream_started_at_ms = int(started * 1000)
        try:
            async for chunk_data in llm_client.stream_chat_with_context(
                system_prompt=state.prompt_state.system_prompt_text,
                history=history_dicts,
                current_message=state.input_payload.raw_user_message,
                trace_id=state.runtime.trace_id,
                disambiguated_text=state.route_state.disambiguated_text or state.input_payload.raw_user_message,
                session_id=state.runtime.session_id,
                message_id=state.generation_state.assistant_message_id,
            ):
                if chunk_data.get("error"):
                    state.generation_state.error = str(chunk_data.get("error"))
                    logger.error(
                        f"LLM 返回流式错误 trace_id={state.runtime.trace_id} error={state.generation_state.error}"
                    )
                if first_chunk and chunk_data.get("chunk"):
                    state.generation_state.ttft_ms = int((time.time() - started) * 1000)
                    first_chunk = False
                for msg_type, content in parser.feed(chunk_data.get("chunk", "")):
                    await _handle_stream_piece(state, msg_type, content, False, self.dependencies.event_publisher)
                if chunk_data.get("is_finished", False):
                    flushed = parser.flush()
                    if not flushed:
                        await _publish_stream_payload(
                            state,
                            CHAT_STREAM_TYPE_REPLY_CHUNK,
                            "",
                            True,
                            self.dependencies.event_publisher,
                            error=chunk_data.get("error") or "",
                        )
                    else:
                        for msg_type, content in flushed:
                            await _handle_stream_piece(state, msg_type, content, True, self.dependencies.event_publisher)
                    state.generation_state.finish_reason = chunk_data.get("finish_reason") or "stop"
                    break
            if not state.generation_state.full_text and not state.generation_state.error:
                state.generation_state.error = CHAT_STREAM_EMPTY_RESPONSE_ERROR
        except Exception as exc:
            state.generation_state.error = str(exc)
            await _publish_stream_payload(
                state,
                CHAT_STREAM_TYPE_REPLY_CHUNK,
                "",
                True,
                self.dependencies.event_publisher,
                error=str(exc),
            )
            state.error_state = ChatErrorState(
                node_type=self.node_type,
                error_code=ChatWorkflowErrorCode.MAIN_LLM_FAILED.value,
                message=f"主模型生成失败: {exc}",
                recoverable=False,
            )
            raise RuntimeError(state.error_state.message) from exc
        return state


class ResponsePersistenceNode(ChatWorkflowNode):
    """回复落盘节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.RESPONSE_PERSISTENCE,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        assistant_content = state.generation_state.full_text
        error_json = ""
        if state.generation_state.error:
            error_json = json.dumps(
                {"error": CHAT_STREAM_GENERATION_ERROR, "details": state.generation_state.error},
                ensure_ascii=False,
            )
            if not assistant_content:
                assistant_content = error_json
        elif not assistant_content:
            error_json = json.dumps(
                {"error": CHAT_STREAM_GENERATION_ERROR, "details": CHAT_STREAM_EMPTY_RESPONSE_ERROR},
                ensure_ascii=False,
            )
            assistant_content = error_json
        now_ts = int(time.time())
        interaction = Interaction(
            msgId=state.generation_state.assistant_message_id,
            userContent=state.input_payload.raw_user_message,
            assistantContent=assistant_content,
            thought=state.generation_state.thought_text,
            emotion=state.generation_state.emotion,
            error=error_json,
            timestamp=now_ts,
        )
        pg_status = CHAT_WORKFLOW_PG_WRITE_SKIPPED
        redis_status = CHAT_WORKFLOW_REDIS_WRITE_SKIPPED
        if self.dependencies.pg_repo:
            try:
                await self.dependencies.pg_repo.save_interaction(
                    InteractionModel(
                        id=generate_string_id(),
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        user_content=state.input_payload.raw_user_message,
                        assistant_content=assistant_content,
                        thought=state.generation_state.thought_text,
                        emotion=state.generation_state.emotion,
                        error=error_json,
                    )
                )
                pg_status = CHAT_WORKFLOW_PG_WRITE_OK
            except Exception as exc:
                pg_status = CHAT_WORKFLOW_PG_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 PG 失败 trace_id={state.runtime.trace_id} error={exc}")
        if self.dependencies.redis_repo:
            try:
                length = await self.dependencies.redis_repo.save_interaction(state.runtime.session_id, interaction)
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_OK
                state.postprocess_state.should_run_memory_compression = length > 50
                state.postprocess_state.should_run_profile_extraction = length > 50
            except Exception as exc:
                redis_status = CHAT_WORKFLOW_REDIS_WRITE_FAILED
                logger.error(f"Workflow 保存 Interaction 到 Redis 失败 trace_id={state.runtime.trace_id} error={exc}")
        logger.info(
            f"回复持久化完成 trace_id={state.runtime.trace_id} interaction_id={state.runtime.interaction_id} "
            f"session_id={state.runtime.session_id} node_type={self.node_type.value} pg_status={pg_status} redis_status={redis_status}"
        )
        return state


class LongTermMemoryCompressionNode(ChatWorkflowNode):
    """长期记忆压缩后处理节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_COMPRESSION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        if not state.postprocess_state.should_run_memory_compression:
            return state
        try:
            state.postprocess_state.memory_mutation_staging.append(
                MemoryMutationCandidate(
                    content=state.generation_state.full_text,
                    source=state.runtime.session_id,
                    metadata={},
                )
            )
        except Exception as exc:
            state.postprocess_state.postprocess_errors.append(
                PostprocessError(node_type=self.node_type, message=str(exc), retryable=True)
            )
        return state


class UserProfileExtractionNode(ChatWorkflowNode):
    """用户画像提取后处理节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.USER_PROFILE_EXTRACTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        if not state.postprocess_state.should_run_profile_extraction or not self.dependencies.user_profile_service:
            return state
        messages_text = f"用户: {state.input_payload.raw_user_message}\nLuna: {state.generation_state.full_text}\n"
        try:
            self.dependencies.user_profile_service.start_extract_from_messages(
                user_id=state.runtime.user_id,
                session_id=state.runtime.session_id,
                messages_text=messages_text,
                trace_id=state.runtime.trace_id,
            )
        except Exception as exc:
            state.postprocess_state.postprocess_errors.append(
                PostprocessError(node_type=self.node_type, message=str(exc), retryable=True)
            )
        return state


class PostprocessCommitNode(ChatWorkflowNode):
    """成功态提交节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.POSTPROCESS_COMMIT,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.postprocess_state.committed = not state.postprocess_state.postprocess_errors
        logger.info(
            f"后处理提交节点完成 trace_id={state.runtime.trace_id} interaction_id={state.runtime.interaction_id} "
            f"session_id={state.runtime.session_id} committed={state.postprocess_state.committed} "
            f"reason={CHAT_WORKFLOW_POSTPROCESS_SUCCESS_REASON}"
        )
        return state


class FinalizeNode(ChatWorkflowNode):
    """结束归档节点。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.FINALIZE,
            event_publisher=dependencies.event_publisher,
        )

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        state.runtime.current_node_type = ChatWorkflowNodeType.FINALIZE
        return state


def _format_recent_history(history: list[Interaction]) -> str:
    """把 Redis 短期窗口转换为 Prompt 可读文本。"""
    parts: list[str] = []
    for index, item in enumerate(history):
        parts.append(f"[对话 {index + 1}]\n")
        parts.append(f"用户: {item.userContent}\n")
        if item.assistantContent:
            parts.append(f"Luna: {item.assistantContent}\n")
        if item.thought:
            parts.append(f"(内心独白: {item.thought})\n")
        if item.emotion:
            parts.append(f"(心情: {item.emotion})\n")
        if item.error:
            parts.append(f"(错误: {item.error})\n")
        if item.timestamp:
            parts.append(f"(时间: {datetime.fromtimestamp(item.timestamp).strftime('%Y-%m-%d %H:%M:%S %A')})\n")
        parts.append("\n")
    return "".join(parts)


def _split_key_facts(value: str) -> list[str]:
    """把摘要中的关键事实文本拆成列表。"""
    return [line.strip() for line in value.splitlines() if line.strip()]


def _first_reason(reasons: list[str], fallback: str) -> str:
    """读取首个非空路由原因。"""
    for reason in reasons:
        if reason:
            return reason
    return fallback


def _history_to_model_messages(history: list[Interaction]) -> list[dict[str, str]]:
    """把历史 Interaction 转为 LLM 对话上下文。"""
    messages: list[dict[str, str]] = []
    for item in history:
        messages.append({"role": Role.USER.value, "content": item.userContent})
        messages.append({"role": Role.ASSISTANT.value, "content": item.error or item.assistantContent})
    return messages


async def _handle_stream_piece(
    state: ChatWorkflowState,
    msg_type: str,
    content: str,
    is_finished: bool,
    event_publisher: ChatWorkflowEventPublisher | None,
) -> None:
    """处理 StreamParser 输出的结构化片段并转发给前端。"""
    if msg_type == CHAT_STREAM_TYPE_REPLY_CHUNK:
        state.generation_state.full_text += content
    elif msg_type == CHAT_STREAM_TYPE_THOUGHT_CONTENT:
        state.generation_state.thought_text += content
    elif msg_type == CHAT_STREAM_TYPE_EMOTION_UPDATE:
        state.generation_state.emotion = content
    if msg_type != CHAT_STREAM_TYPE_THOUGHT_CONTENT:
        await _publish_stream_payload(state, msg_type, content, is_finished, event_publisher)


async def _publish_stream_payload(
    state: ChatWorkflowState,
    msg_type: str,
    content: str,
    is_finished: bool,
    event_publisher: ChatWorkflowEventPublisher | None,
    *,
    error: str = "",
) -> None:
    """发布兼容既有 CHAT_STREAM 的流式载荷。"""
    if not event_publisher:
        return
    from app.types.constants import WS_MSG_TYPE_CHAT_STREAM
    from app.api.sse import sse_manager

    payload = ChatStreamChunkPayload(
        type=msg_type,
        chunk=content,
        is_finished=is_finished,
        node_id=state.generation_state.assistant_message_id,
        error=error,
        interaction_id=state.runtime.interaction_id,
        assistant_message_id=state.generation_state.assistant_message_id,
        plan_preset_id=state.runtime.plan_preset_id,
        current_node_type=ChatWorkflowNodeType.MAIN_CHAT_LLM,
        citations=[item.model_dump(mode="json") for item in state.generation_state.citations],
        is_final_chunk=is_finished,
    )
    await sse_manager.publish(
        {
            "type": WS_MSG_TYPE_CHAT_STREAM,
            "trace_id": state.runtime.trace_id,
            "payload": payload.model_dump(mode="json"),
        }
    )
