"""Phase 8.5 Chat Workflow 条件路由模块。

做什么：集中定义长期记忆 RAG 与知识库 RAG 条件边评估、旁路汇合节点和条件事件发送。
        旁路节点同时发布 EVT_CHAT_STATUS SKIPPED 状态，确保前端不会因为条件未命中
        而陷入"等待某个阶段超时"的困惑。
为什么这样做：条件节点未进入不是静默跳过，必须记录 NOT_ENTERED_BY_CONDITION 与
            EVT_CHAT_CONDITION_EVALUATED；同时 SKIPPED 状态让前端可观测到阶段被跳过。
"""

from __future__ import annotations

import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
    CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
    CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
    ChatConditionalRoute,
    ChatNodeStatus,
    ChatWorkflowEventType,
    ChatWorkflowGraphNodeName,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.events import ChatConditionEvaluatedPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher


class ChatWorkflowRouter:
    """Chat Workflow 条件路由器。"""

    def __init__(
        self,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """绑定事件发布器，供条件边评估时输出调试事件及 Chat 状态。"""
        self.event_publisher = event_publisher
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def route_long_term_memory(self, graph_state: dict[str, Any]) -> str:
        """评估是否进入长期记忆 RAG 条件节点。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_long_term_memory_rag
        reason = _first_reason(
            [state.route_state.route_reasons[0]] if state.route_state.route_reasons else [],
            CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
        )
        # v3.1 修复：source_node_type 已从 SESSION_CONTEXT_LOAD 更新为 INPUT_RECONSTRUCTION。
        # 为什么这样做：输入重构与会话上下文加载的执行顺序已交换，输入重构放在会话上下文
        # 加载之后执行。现在条件路由路由出自分输入重构节点。
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.INPUT_RECONSTRUCTION,
            target_node_type=ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_LONG_TERM_MEMORY_RAG
                if entered
                else ChatConditionalRoute.BYPASS_LONG_TERM_MEMORY_RAG
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_RAG.value
            if entered
            else ChatWorkflowGraphNodeName.LONG_TERM_MEMORY_BYPASS.value
        )

    async def route_knowledge_rag(self, graph_state: dict[str, Any]) -> str:
        """评估是否进入知识库 RAG 条件节点。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_knowledge_rag
        reason = _first_reason(
            [state.route_state.route_reasons[1]] if len(state.route_state.route_reasons) > 1 else [],
            CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
        )
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.USER_PROFILE_INJECTION,
            target_node_type=ChatWorkflowNodeType.KNOWLEDGE_RAG,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_KNOWLEDGE_RAG
                if entered
                else ChatConditionalRoute.BYPASS_KNOWLEDGE_RAG
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.KNOWLEDGE_RAG.value
            if entered
            else ChatWorkflowGraphNodeName.KNOWLEDGE_RAG_BYPASS.value
        )

    async def bypass_long_term_memory(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """长期记忆条件未进入时写入显式观测记录、推送 SKIPPED 状态并汇合。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        reason = _first_reason(
            [state.route_state.route_reasons[0]] if state.route_state.route_reasons else [],
            CHAT_WORKFLOW_NO_MEMORY_ROUTE_REASON,
        )
        _append_not_entered_observation(state, ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG, reason)

        # 发布 EVT_CHAT_STATUS：长期记忆阶段被跳过（SKIPPED，不可见）
        await self.chat_status_publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=ChatStatusStage.RAG_RETRIEVAL,
            state=ChatStatusState.SKIPPED,
            display_text="",
            is_visible=False,
            is_terminal=True,
        )

        return state.as_graph_state()

    async def bypass_knowledge_rag(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """知识库 RAG 条件未进入时写入显式观测记录、推送 SKIPPED 状态并汇合。"""
        state = ChatWorkflowState.from_graph_state(graph_state)
        reason = _first_reason(
            [state.route_state.route_reasons[1]] if len(state.route_state.route_reasons) > 1 else [],
            CHAT_WORKFLOW_NO_KNOWLEDGE_ROUTE_REASON,
        )
        _append_not_entered_observation(state, ChatWorkflowNodeType.KNOWLEDGE_RAG, reason)

        # 发布 EVT_CHAT_STATUS：知识库 RAG 阶段被跳过（SKIPPED，不可见）
        await self.chat_status_publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=ChatStatusStage.KNOWLEDGE_RAG,
            state=ChatStatusState.SKIPPED,
            display_text="",
            is_visible=False,
            is_terminal=True,
        )

        return state.as_graph_state()

    # ---- Phase 12（v3.0）新增：MCP Skill 条件路由 ----

    async def route_mcp_skill(self, graph_state: dict[str, Any]) -> str:
        """
        评估是否进入 MCP Skill 执行节点。

        做什么：根据输入重构节点输出的 skill_judgment.need_skill 判断是否进入 Skill 节点。
        为什么这样做：Skill 节点与 MCP Tool 节点处于同等的条件分支地位。
        参数:
            graph_state: LangGraph 传递的字典状态。
        返回:
            str: MCP_SKILL_EXECUTION 或 MCP_SKILL_BYPASS 的 LangGraph 节点名称。
        """
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_skill
        reason = (
            f"输入重构判定需要技能调用: "
            f"{state.route_state.skill_judgment_json.get('reason', '') if state.route_state.skill_judgment_json else ''}"
            if entered
            else CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON
        )
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.INPUT_RECONSTRUCTION,
            target_node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_MCP_SKILL
                if entered
                else ChatConditionalRoute.BYPASS_MCP_SKILL
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value
            if entered
            else ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value
        )

    async def bypass_mcp_skill(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """
        MCP Skill 条件未进入时写入显式观测记录、推送 SKIPPED 状态并汇合。

        做什么：当输入重构判定不需要技能调用时，记录观测并跳过 Skill 节点。
        """
        state = ChatWorkflowState.from_graph_state(graph_state)
        _append_not_entered_observation(
            state, ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
            CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
        )

        # 发布 EVT_CHAT_STATUS：MCP Skill 阶段被跳过（SKIPPED，不可见）
        await self.chat_status_publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=ChatStatusStage.MCP_SKILL_EXECUTION,
            state=ChatStatusState.SKIPPED,
            display_text="",
            is_visible=False,
            is_terminal=True,
        )

        return state.as_graph_state()

    # ---- Phase 12（v3.0）新增：MCP 前置判断后的 Skill 路由 ----

    async def route_mcp_skill_from_judge(self, graph_state: dict[str, Any]) -> str:
        """
        评估是否从 MCP 前置判断节点进入 MCP Skill 执行节点。

        做什么：根据 MCP 前置判断节点的判定结果（should_enter_skill）路由。
        为什么这样做：与原有的 route_mcp_skill 逻辑一致，但来源节点不同（
                    原来源为 INPUT_RECONSTRUCTION，新来源为 MCP_INTENT_JUDGE）。
        """
        state = ChatWorkflowState.from_graph_state(graph_state)
        entered = state.route_state.should_enter_skill
        reason = (
            f"MCP 前置判断需要技能调用: "
            f"{state.route_state.skill_judgment_json.get('reason', '') if state.route_state.skill_judgment_json else ''}"
            if entered
            else CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON
        )
        await self._publish_condition(
            state=state,
            source_node_type=ChatWorkflowNodeType.MCP_INTENT_JUDGE,
            target_node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
            condition_entered=entered,
            route_name=(
                ChatConditionalRoute.ENTER_MCP_SKILL_FROM_JUDGE
                if entered
                else ChatConditionalRoute.BYPASS_MCP_SKILL_FROM_JUDGE
            ),
            reason=reason,
        )
        return (
            ChatWorkflowGraphNodeName.MCP_SKILL_EXECUTION.value
            if entered
            else ChatWorkflowGraphNodeName.MCP_SKILL_BYPASS.value
        )

    async def bypass_mcp_intent(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        """
        MCP 前置判断条件未进入时写入显式观测记录、推送 SKIPPED 状态并汇合。

        做什么：当 MCP 前置判断节点判定不需要技能调用时，记录观测并跳转到上下文治理。
        """
        state = ChatWorkflowState.from_graph_state(graph_state)
        _append_not_entered_observation(
            state, ChatWorkflowNodeType.MCP_INTENT_JUDGE,
            CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
        )

        # 发布 EVT_CHAT_STATUS：MCP 前置判断阶段被跳过（SKIPPED，不可见）
        await self.chat_status_publisher.publish(
            trace_id=state.runtime.trace_id,
            session_id=state.runtime.session_id,
            message_id=state.generation_state.assistant_message_id,
            stage=ChatStatusStage.MCP_INTENT_JUDGE,
            state=ChatStatusState.SKIPPED,
            display_text="",
            is_visible=False,
            is_terminal=True,
        )

        return state.as_graph_state()

    async def _publish_condition(
        self,
        *,
        state: ChatWorkflowState,
        source_node_type: ChatWorkflowNodeType,
        target_node_type: ChatWorkflowNodeType,
        condition_entered: bool,
        route_name: ChatConditionalRoute,
        reason: str,
    ) -> None:
        """发布条件评估事件并记录日志。"""
        payload = ChatConditionEvaluatedPayload(
            source_node_type=source_node_type,
            target_node_type=target_node_type,
            condition_entered=condition_entered,
            route_name=route_name,
            reason=reason,
        )
        logger.info(
            f"Chat Workflow 条件边评估 trace_id={state.runtime.trace_id} "
            f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} "
            f"source_node_type={source_node_type.value} target_node_type={target_node_type.value} "
            f"condition_entered={condition_entered} route_name={route_name.value} reason={reason}"
        )
        if not self.event_publisher:
            return
        event = ChatWorkflowEvent(
            event_id=generate_string_id(),
            event_type=ChatWorkflowEventType.EVT_CHAT_CONDITION_EVALUATED,
            trace_id=state.runtime.trace_id,
            interaction_id=state.runtime.interaction_id,
            session_id=state.runtime.session_id,
            plan_preset_id=state.runtime.plan_preset_id,
            node_type=target_node_type,
            timestamp_ms=_now_ms(),
            payload=payload.model_dump(mode="json"),
        )
        state.observability.emitted_event_ids.append(event.event_id)
        try:
            await self.event_publisher.publish(event)
        except Exception as exc:
            logger.warning(f"条件评估事件发布失败 trace_id={state.runtime.trace_id} error={exc}")

    async def route_after_dag_engine(self, graph_state: dict[str, Any]) -> str:
        """DAG 引擎节点之后的条件路由。

        做什么：检查 dag_state.gating_suspended 标志，决定外层图的下一步走向。
                - gating_suspended=True → 跳过 LLM 生成，直接进入 FINALIZE。
                  前端审批面板已展示，工作流应在此暂停等待用户审批。
                - gating_suspended=False → 正常进入 CONTEXT_GOVERNANCE 继续执行。
        为什么这样做：Agent Loop 内层子图在 L2/L3 工具触发 Gating 审批后正确退出，
                     但外层图的 dag_engine_agent_loop → context_governance 是无条件边，
                     如果不加条件路由，外层图会继续执行 context_governance → main_chat_llm，
                     主 Chat LLM 会生成回复，造成"自动同意"的假象。
        路由逻辑：
            - gating_suspended → FINALIZE（跳过 LLM 生成）
            - 否则 → CONTEXT_GOVERNANCE（正常流程）
        """
        state = ChatWorkflowState.from_graph_state(graph_state)
        if state.dag_state.gating_suspended:
            logger.info(
                f"[TraceID:{state.runtime.trace_id}] route_after_dag_engine: "
                f"检测到 gating_suspended，跳过 LLM 生成，直接进入 FINALIZE"
            )
            # 发布 CONTEXT_GOVERNANCE SKIPPED 状态，让前端知道该阶段被跳过
            await self.chat_status_publisher.publish(
                trace_id=state.runtime.trace_id,
                session_id=state.runtime.session_id,
                message_id=state.generation_state.assistant_message_id,
                stage=ChatStatusStage.CONTEXT_GOVERNANCE,
                state=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return ChatWorkflowGraphNodeName.FINALIZE.value
        return ChatWorkflowGraphNodeName.CONTEXT_GOVERNANCE.value


def _append_not_entered_observation(
    state: ChatWorkflowState,
    node_type: ChatWorkflowNodeType,
    reason: str,
) -> None:
    """写入条件未进入节点观测。"""
    now_ms = _now_ms()
    state.observability.node_observations.append(
        {
            "node_type": node_type,
            "status": ChatNodeStatus.NOT_ENTERED_BY_CONDITION,
            "started_at_ms": now_ms,
            "ended_at_ms": now_ms,
            "latency_ms": 0,
            "retry_count": state.runtime.retry_count,
            "condition_entered": False,
            "condition_reason": reason,
        }
    )


def _first_reason(reasons: list[str], fallback: str) -> str:
    """读取首个非空原因。"""
    for reason in reasons:
        if reason:
            return reason
    return fallback


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
