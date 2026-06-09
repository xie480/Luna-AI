"""输入重构节点。"""

from __future__ import annotations

from typing import Any

from app.agent.input_reconstructor import InputReconstructorAgent
from app.logger import logger
from app.prompt.types import PromptCategory
from app.types.constants import DagRouteHint, IntentCategory, PrimaryIntent, RetrievalType
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
        """
        处理输入重构逻辑
        
        Args:
            state (ChatWorkflowState): 当前工作流状态
            
        Returns:
            ChatWorkflowState: 更新后的状态对象
        """
        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)
            return state
        try:
            # 格式化最近的历史消息并存储到状态中
            memory_snippets = format_recent_history(state.session_state.recent_messages)
            state.session_state.memory_snippets = memory_snippets
            
            # 构建系统提示词
            system_prompt = await prompt_manager.assemble_prompt(PromptCategory.INPUT_RECONSTRUCTION, {})
            
            # 构建记忆相关提示词，包含摘要、关键事实和记忆片段
            memory_prompt = await prompt_manager.assemble_prompt(
                PromptCategory.INPUT_RECONSTRUCTION,
                {
                    PROMPT_VARIABLE_CORE_SUMMARY: state.session_state.short_summary,
                    PROMPT_VARIABLE_KEY_FACTS: "\n".join(state.session_state.key_facts),
                    PROMPT_VARIABLE_MEMORY_SNIPPETS: memory_snippets,
                },
            )
            
            # 获取各种枚举类型的值列表用于构建运行时提示
            primary_intents = [item.value for item in PrimaryIntent]
            categories = [item.value for item in IntentCategory]
            dag_route_hints = [item.value for item in DagRouteHint]
            retrieval_types = [item.value for item in RetrievalType]
            
            # 构建运行时提示词，包含用户输入和各类枚举选项
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

            # 调用输入重构代理处理用户输入
            result = await InputReconstructorAgent(llm_client).process(
                trace_id=state.runtime.trace_id,
                user_input=state.input_payload.raw_user_message,
                system_prompt=system_prompt,
                memory_prompt=memory_prompt,
                runtime_prompt=runtime_prompt,
            )
            
            # 解析重构结果
            reconstruction = result.reconstruction
            retrieval_routing = result.retrieval_routing
            required_types = {item.value for item in result.intent_routing.required_retrieval_types}
            long_term = retrieval_routing.long_term_memory
            external = retrieval_routing.external_knowledge
            
            # 更新状态中的重构文本信息
            state.route_state.reconstructed_text = state.input_payload.raw_user_message
            state.route_state.disambiguated_text = (
                reconstruction.disambiguated_text or state.input_payload.raw_user_message
            )
            state.route_state.user_intent_summary = result.intent_routing.category.value
            
            # 设置是否需要进入长期记忆RAG和外部知识RAG
            state.route_state.should_enter_long_term_memory_rag = (
                RetrievalType.LONG_TERM_MEMORY.value in required_types and long_term.trigger
            )
            state.route_state.should_enter_knowledge_rag = (
                RetrievalType.EXTERNAL_KNOWLEDGE.value in required_types and external.trigger
            )
            
            # 更新长期记忆相关的查询和实体信息
            state.route_state.search_queries = long_term.search_queries
            state.route_state.entity_mentions = long_term.entity_mentions
            state.route_state.temporal_focus = long_term.temporal_focus.model_dump(mode="json")
            
            # 更新外部知识相关的查询和实体信息
            state.route_state.external_search_queries = external.search_queries
            state.route_state.external_entity_mentions = external.entity_mentions
            state.route_state.external_temporal_focus = (
                external.temporal_focus.model_dump(mode="json") if external.temporal_focus else {}
            )
            
            # 设置知识路由策略和原因
            state.route_state.knowledge_route = retrieval_routing.route_strategy
            state.route_state.route_reasons = [
                long_term.trigger_reason or CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
                external.trigger_reason or CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
            ]
            
            # 设置情感状态
            state.route_state.emotion_state = result.emotion_state.model_dump(mode="json")
            return state
        except Exception as exc:
            logger.warning(
                f"输入重构节点降级 trace_id={state.runtime.trace_id} "
                f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} error={exc}"
            )
            self._apply_rule_fallback(state, CHAT_WORKFLOW_INPUT_RECONSTRUCTION_DEGRADED_REASON)
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
