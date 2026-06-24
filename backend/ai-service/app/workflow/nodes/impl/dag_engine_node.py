"""Phase 9 DAG 引擎 — LangGraph 节点包装器。

做什么：将 Plan + Cursor 子图或 Agent Loop 子图包装为 LangGraph 外层图的可调用节点。
为什么这样做：LangGraph 的 StateGraph 需要一个 async 函数作为节点，
              子图是独立的 CompiledGraph，需要一个适配层将其包装为外层图的节点。
              支持两种子图模式：原 Plan + Cursor（plan_state_node）和 Agent Loop（agent_loop）。
"""

from __future__ import annotations

import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.workflow.constants import ChatNodeStatus, ChatWorkflowEventType, ChatWorkflowNodeType
from app.workflow.context import ChatWorkflowState
from app.workflow.events import ChatNodeStatusPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher


class DagEngineNode:
    """DAG 引擎 LangGraph 节点包装器。

    做什么：将子图包装为 LangGraph 外层图的节点函数。
    为什么这样做：外层图看到的 DAG_ENGINE 仍然是一个节点，
                  内部根据构造参数选择 Plan + Cursor 子图或 Agent Loop 子图。
    """

    def __init__(
        self,
        plan_cursor_subgraph: Any = None,
        agent_loop_subgraph: Any = None,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 DAG 引擎节点。

        参数:
            plan_cursor_subgraph: 编译后的 Plan + Cursor 子图（CompiledGraph）。
            agent_loop_subgraph: 编译后的 Agent Loop 子图（CompiledGraph）。
            event_publisher: 工作流事件发布器。
            chat_status_publisher: Chat 状态发布器。
        """
        self.plan_cursor_subgraph = plan_cursor_subgraph
        self.agent_loop_subgraph = agent_loop_subgraph
        # 选择实际使用的子图：优先 Agent Loop，回退到 Plan + Cursor
        self._active_subgraph = agent_loop_subgraph or plan_cursor_subgraph
        self.event_publisher = event_publisher
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口。

        做什么：
        1. 从外层图状态反序列化 ChatWorkflowState
        2. 发布节点开始事件
        3. 调用 Agent Loop 子图 ainvoke()
        4. 从子图结果恢复 ChatWorkflowState
        5. 发布节点完成/失败事件
        6. 返回更新后的图状态
        """
        chat_state = ChatWorkflowState.from_graph_state(state)

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        started_at_ms = _now_ms()

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
            # 调用编译后的子图（根据初始化时选择的子图类型）
            subgraph_result = await self._active_subgraph.ainvoke(
                chat_state.as_graph_state()
            )

            # 从子图结果恢复 ChatWorkflowState
            chat_state = ChatWorkflowState.from_graph_state(subgraph_result)

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
                f"[TraceID:{trace_id}] DAG 引擎 Agent Loop 子图执行异常: {exc}"
            )
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


def _now_ms() -> int:
    """获取当前时间戳（毫秒）。"""
    return int(time.time() * 1000)
