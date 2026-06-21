"""Phase 9 DAG 引擎 — LangGraph 节点包装器。

做什么：将 DagEngine 包装为 LangGraph 可调用的节点函数。
为什么这样做：LangGraph 的 StateGraph 需要一个 async 函数作为节点，
              DagEngine 是独立的调度系统，需要一个适配层。
"""

from __future__ import annotations

import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.workflow.constants import ChatNodeStatus, ChatWorkflowEventType, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.dag.engine import DagEngine
from app.workflow.dag.types import DagEngineState, GlobalObjective
from app.workflow.events import ChatNodeStatusPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher
from app.workflow.nodes.base import _now_ms
from app.utils.snowflake import generate_string_id


class DagEngineNode:
    """DAG 引擎 LangGraph 节点包装器。

    做什么：将 DagEngine 包装为 LangGraph 的节点函数。
    为什么这样做：LangGraph 节点签名必须是 async (state: dict) -> dict，
                  DagEngine 内部是独立的 Plan + Cursor 循环。
    """

    def __init__(
        self,
        dag_engine: DagEngine,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 DAG 引擎节点。

        参数:
            dag_engine: DAG 引擎实例。
            event_publisher: 工作流事件发布器。
            chat_status_publisher: Chat 状态发布器。
        """
        self.dag_engine = dag_engine
        self.event_publisher = event_publisher
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口。

        做什么：
        1. 从 ChatWorkflowState 提取上下文
        2. 构建 DagEngineState
        3. 调用 DagEngine.run()
        4. 将结果写回 ChatWorkflowState
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        started_at_ms = _now_ms()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 发布节点开始事件
        if self.event_publisher:
            start_event = ChatWorkflowEvent(
                event_id=generate_string_id(),
                event_type=ChatWorkflowEventType.EVT_CHAT_NODE_STARTED,
                trace_id=trace_id,
                interaction_id=chat_state.runtime.interaction_id,
                session_id=session_id,
                plan_preset_id=chat_state.runtime.plan_preset_id,
                node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
                timestamp_ms=started_at_ms,
                payload=ChatNodeStatusPayload(
                    node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION.value,
                    status=ChatNodeStatus.RUNNING,
                ).model_dump(mode="json"),
            )
            chat_state.observability.emitted_event_ids.append(start_event.event_id)
            try:
                await self.event_publisher.publish(start_event)
            except Exception as exc:
                logger.warning(f"DAG 引擎节点事件发布失败: {exc}")

        try:
            # 构建 DagEngineState
            dag_state = self._build_dag_state(chat_state)

            # 执行 DAG 引擎
            dag_state = await self.dag_engine.run(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
            )

            # 将结果写回 ChatWorkflowState
            self._apply_dag_result(chat_state, dag_state)

            # 发布节点完成事件
            ended_at_ms = _now_ms()
            if self.event_publisher:
                completed_event = ChatWorkflowEvent(
                    event_id=generate_string_id(),
                    event_type=ChatWorkflowEventType.EVT_CHAT_NODE_COMPLETED,
                    trace_id=trace_id,
                    interaction_id=chat_state.runtime.interaction_id,
                    session_id=session_id,
                    plan_preset_id=chat_state.runtime.plan_preset_id,
                    node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
                    timestamp_ms=ended_at_ms,
                    payload=ChatNodeStatusPayload(
                        node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION.value,
                        status=ChatNodeStatus.SUCCEEDED,
                        duration_ms=ended_at_ms - started_at_ms,
                    ).model_dump(mode="json"),
                )
                chat_state.observability.emitted_event_ids.append(completed_event.event_id)
                try:
                    await self.event_publisher.publish(completed_event)
                except Exception as exc:
                    logger.warning(f"DAG 引擎完成事件发布失败: {exc}")

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] DAG 引擎执行异常: {exc}"
            )
            # 发布节点失败事件
            ended_at_ms = _now_ms()
            if self.event_publisher:
                failed_event = ChatWorkflowEvent(
                    event_id=generate_string_id(),
                    event_type=ChatWorkflowEventType.EVT_CHAT_NODE_FAILED,
                    trace_id=trace_id,
                    interaction_id=chat_state.runtime.interaction_id,
                    session_id=session_id,
                    plan_preset_id=chat_state.runtime.plan_preset_id,
                    node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
                    timestamp_ms=ended_at_ms,
                    payload=ChatNodeStatusPayload(
                        node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION.value,
                        status="failed",
                        error_message=str(exc),
                        duration_ms=ended_at_ms - started_at_ms,
                    ).model_dump(mode="json"),
                )
                chat_state.observability.emitted_event_ids.append(failed_event.event_id)
                try:
                    await self.event_publisher.publish(failed_event)
                except Exception as pub_exc:
                    logger.warning(f"DAG 引擎失败事件发布失败: {pub_exc}")
                raise

        return chat_state.as_graph_state()

    def _build_dag_state(self, chat_state: ChatWorkflowState) -> DagEngineState:
        """从 ChatWorkflowState 构建 DagEngineState。

        做什么：提取必要的上下文数据，构建 DAG 引擎的初始状态。
        """
        return DagEngineState(
            disambiguated_text=chat_state.dag_state.disambiguated_text
                or chat_state.input_payload.raw_user_message,
            unresolved_pronouns=chat_state.dag_state.unresolved_pronouns,
            session_context={
                "memory_snippets": chat_state.session_state.memory_snippets,
                "key_facts": chat_state.session_state.key_facts,
                "short_summary": chat_state.session_state.short_summary,
                "recent_messages": chat_state.session_state.recent_messages,
            },
            user_profile={
                "prompt_profile_text": chat_state.profile_state.prompt_profile_text,
            },
            memory_context=chat_state.memory_state.prompt_memory_text,
            workflow_state=chat_state.model_dump(mode="json"),
        )

    def _apply_dag_result(
        self,
        chat_state: ChatWorkflowState,
        dag_state: DagEngineState,
    ) -> None:
        """将 DAG 引擎结果写回 ChatWorkflowState。

        做什么：将 Plan 汇总结果、终止上下文等写入 dag_state 字段。
        """
        chat_state.dag_state.is_dag_active = True
        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
        chat_state.dag_state.disambiguated_text = dag_state.disambiguated_text
        chat_state.dag_state.unresolved_pronouns = dag_state.unresolved_pronouns

        # 写入 Plan 汇总结果
        summary = dag_state.plan_summary
        if summary:
            chat_state.dag_state.plan_summary_text = summary.get(
                "overall_result", ""
            )

        # 写入终止上下文
        if dag_state.terminated:
            chat_state.dag_state.terminated = True
            chat_state.dag_state.termination_reason = dag_state.termination_reason
            partial_parts = []
            for sid, runtime in dag_state.state_runtimes.items():
                if runtime.get("status") == "SUCCEEDED":
                    partial_parts.append(
                        f"- {runtime.get('intent', '')}: {runtime.get('goal', '')}"
                    )
            chat_state.dag_state.partial_results = "\n".join(partial_parts)

        # 将 DAG 汇总结果注入到 MCP tool state 的 execution_summary
        # 这样主 Chat LLM 可以通过 SKILL_EXECUTION_SUMMARY 变量获取结果
        if summary and summary.get("overall_result"):
            chat_state.mcp_tool_state.execution_summary = summary.get(
                "overall_result", ""
            )
