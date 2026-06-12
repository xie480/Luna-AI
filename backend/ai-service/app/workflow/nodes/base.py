"""
Phase 8.5 Chat Workflow 节点基类与观测工具。

做什么：为所有节点提供统一的开始、完成、失败、降级观测记录和 SSE 事件发送能力。
为什么这样做：节点适配层必须具备一致的 trace_id、interaction_id、session_id、node_type、latency_ms 观测字段。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.workflow.constants import ChatNodeStatus, ChatWorkflowEventType, ChatWorkflowNodeType
from app.workflow.context import ChatNodeObservation, ChatWorkflowState
from app.workflow.events import ChatNodeStatusPayload, ChatWorkflowEvent, ChatWorkflowEventPublisher


class ChatWorkflowNode:
    """Chat Workflow 节点基类。"""

    def __init__(
        self,
        *,
        node_type: ChatWorkflowNodeType,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """
        初始化节点。

        做什么：绑定节点类型和事件发布器。
        为什么这样做：所有节点都必须通过同一字段记录当前节点和事件。
        输入输出：输入节点类型与可选事件发布器；节点实例作为 LangGraph adapter 复用。
        边界条件：event_publisher 为空时只记录日志和状态，不发送 SSE。
        异常行为：初始化不抛业务异常。
        """
        self.node_type = node_type
        self.event_publisher = event_publisher

    async def run_with_observation(
        self,
        state: ChatWorkflowState | dict[str, Any],
        handler: Callable[[ChatWorkflowState], Awaitable[ChatWorkflowState]],
    ) -> dict[str, Any]:
        """
        包装节点执行并记录统一观测。

        做什么：在执行前写入 RUNNING，执行后根据节点状态写入 SUCCEEDED/DEGRADED，异常时写入 FAILED。
        为什么这样做：避免每个节点重复编写观测逻辑，保证 Phase 8.5 验收字段完整。
        输入输出：输入根状态和节点处理函数，输出 LangGraph 可传播字典状态。
        边界条件：handler 可以返回同一状态对象或新状态对象。
        异常行为：handler 异常会写入 error_state 并重新抛出，主链路阻断节点由 Service 归一化。
        
        Args:
            state: 当前工作流状态，可以是 ChatWorkflowState 对象或字典
            handler: 处理节点逻辑的异步函数，接收 ChatWorkflowState 返回新的 ChatWorkflowState
            
        Returns:
            dict[str, Any]: LangGraph 可传播的字典状态
        """
        # 将输入状态转换为类型化的 ChatWorkflowState 对象
        typed_state = ChatWorkflowState.from_graph_state(state)
        # 记录开始时间戳
        started_at_ms = _now_ms()
        # 设置当前节点类型到运行时信息中
        typed_state.runtime.current_node_type = self.node_type
        
        # 初始状态记录为 RUNNING
        await self._append_observation(
            state=typed_state,
            status=ChatNodeStatus.RUNNING,
            started_at_ms=started_at_ms,
        )
        # 发布节点状态为 RUNNING
        await self._publish_node_status(
            state=typed_state,
            status=ChatNodeStatus.RUNNING,
            started_at_ms=started_at_ms,
        )
        try:
            # 执行处理函数
            next_state = await handler(typed_state)
            
            # 初始化状态为成功
            status = ChatNodeStatus.SUCCEEDED
            degraded_reason = ""
            
            # 检查节点是否处于降级状态
            if self._is_node_degraded(next_state):
                status = ChatNodeStatus.DEGRADED
                degraded_reason = self._degraded_reason(next_state)
                
            # 计算结束时间和延迟
            ended_at_ms = _now_ms()
            latency_ms = max(0, ended_at_ms - started_at_ms)
            
            # 记录成功或降级状态的观测信息
            await self._append_observation(
                state=next_state,
                status=status,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                latency_ms=latency_ms,
                degraded_reason=degraded_reason,
            )
            # 发布成功或降级状态
            await self._publish_node_status(
                state=next_state,
                status=status,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                latency_ms=latency_ms,
                degraded_reason=degraded_reason,
            )
            
            # 记录节点执行完成的日志
            logger.info(
                f"Chat Workflow 节点执行完成 trace_id={next_state.runtime.trace_id} "
                f"interaction_id={next_state.runtime.interaction_id} session_id={next_state.runtime.session_id} "
                f"node_type={self.node_type.value} status={status.value} latency_ms={latency_ms} "
                f"retry_count={next_state.runtime.retry_count} degraded_reason={degraded_reason} error_code="
            )
            
            # 返回转换为图状态的下一个状态
            return next_state.as_graph_state()
        except Exception as exc:
            # 计算结束时间和延迟
            ended_at_ms = _now_ms()
            latency_ms = max(0, ended_at_ms - started_at_ms)
            
            # 记录失败状态的观测信息
            await self._append_observation(
                state=typed_state,
                status=ChatNodeStatus.FAILED,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                latency_ms=latency_ms,
                error_code=type(exc).__qualname__,
            )
            # 发布失败状态
            await self._publish_node_status(
                state=typed_state,
                status=ChatNodeStatus.FAILED,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                latency_ms=latency_ms,
                error_code=type(exc).__qualname__,
            )
            
            # 记录错误日志
            logger.opt(exception=exc).error(
                f"Chat Workflow 节点执行失败 trace_id={typed_state.runtime.trace_id} "
                f"interaction_id={typed_state.runtime.interaction_id} session_id={typed_state.runtime.session_id} "
                f"node_type={self.node_type.value} status={ChatNodeStatus.FAILED.value} "
                f"latency_ms={latency_ms} retry_count={typed_state.runtime.retry_count} error_code={type(exc).__qualname__}"
            )
            
            # 重新抛出异常
            raise

    async def _append_observation(
        self,
        *,
        state: ChatWorkflowState,
        status: ChatNodeStatus,
        started_at_ms: int,
        ended_at_ms: int | None = None,
        latency_ms: int | None = None,
        condition_entered: bool | None = None,
        condition_reason: str = "",
        degraded_reason: str = "",
        error_code: str = "",
    ) -> None:
        """追加节点观测记录。"""
        state.observability.node_observations.append(
            ChatNodeObservation(
                node_type=self.node_type,
                status=status,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                latency_ms=latency_ms,
                retry_count=state.runtime.retry_count,
                condition_entered=condition_entered,
                condition_reason=condition_reason,
                degraded_reason=degraded_reason,
                error_code=error_code,
            )
        )

    async def _publish_node_status(
        self,
        *,
        state: ChatWorkflowState,
        status: ChatNodeStatus,
        started_at_ms: int | None = None,
        ended_at_ms: int | None = None,
        latency_ms: int | None = None,
        degraded_reason: str = "",
        error_code: str = "",
    ) -> None:
        """发布节点状态事件。"""
        if not self.event_publisher:
            return
        event_type = ChatWorkflowEventType.EVT_CHAT_NODE_COMPLETED
        if status == ChatNodeStatus.RUNNING:
            event_type = ChatWorkflowEventType.EVT_CHAT_NODE_STARTED
        elif status == ChatNodeStatus.FAILED:
            event_type = ChatWorkflowEventType.EVT_CHAT_NODE_FAILED
        elif status == ChatNodeStatus.DEGRADED:
            event_type = ChatWorkflowEventType.EVT_CHAT_NODE_DEGRADED
        payload = ChatNodeStatusPayload(
            node_type=self.node_type,
            status=status,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            latency_ms=latency_ms,
            degraded_reason=degraded_reason,
            error_code=error_code,
        )
        event = ChatWorkflowEvent(
            event_id=generate_string_id(),
            event_type=event_type,
            trace_id=state.runtime.trace_id,
            interaction_id=state.runtime.interaction_id,
            session_id=state.runtime.session_id,
            plan_preset_id=state.runtime.plan_preset_id,
            node_type=self.node_type,
            timestamp_ms=_now_ms(),
            payload=payload.model_dump(mode="json"),
        )
        state.observability.emitted_event_ids.append(event.event_id)
        try:
            await self.event_publisher.publish(event)
        except Exception as exc:
            logger.warning(
                f"Chat Workflow 节点事件发布失败 trace_id={state.runtime.trace_id} "
                f"interaction_id={state.runtime.interaction_id} session_id={state.runtime.session_id} "
                f"node_type={self.node_type.value} error={exc}"
            )

    def _is_node_degraded(self, state: ChatWorkflowState) -> bool:
        """判断当前节点是否处于降级状态。"""
        if self.node_type == ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG:
            return state.memory_state.degraded
        if self.node_type == ChatWorkflowNodeType.USER_PROFILE_INJECTION:
            return state.profile_state.degraded
        if self.node_type == ChatWorkflowNodeType.KNOWLEDGE_RAG:
            return state.knowledge_state.degraded
        # --- Phase 12 新增：MCP 工具执行节点降级检测 ---
        if self.node_type == ChatWorkflowNodeType.MCP_TOOL_EXECUTION:
            return state.mcp_tool_state.degraded
        # --- Phase 12（v3.0）新增：MCP Skill 执行节点降级检测 ---
        if self.node_type == ChatWorkflowNodeType.MCP_SKILL_EXECUTION:
            return state.mcp_tool_state.degraded
        return False

    def _degraded_reason(self, state: ChatWorkflowState) -> str:
        """读取当前节点降级原因。"""
        if self.node_type == ChatWorkflowNodeType.LONG_TERM_MEMORY_RAG:
            return state.memory_state.degraded_reason
        if self.node_type == ChatWorkflowNodeType.USER_PROFILE_INJECTION:
            return state.profile_state.degraded_reason
        if self.node_type == ChatWorkflowNodeType.KNOWLEDGE_RAG:
            return state.knowledge_state.degraded_reason
        # --- Phase 12 新增：MCP 工具执行节点降级原因 ---
        if self.node_type == ChatWorkflowNodeType.MCP_TOOL_EXECUTION:
            return state.mcp_tool_state.degraded_reason
        # --- Phase 12（v3.0）新增：MCP Skill 执行节点降级原因 ---
        if self.node_type == ChatWorkflowNodeType.MCP_SKILL_EXECUTION:
            return state.mcp_tool_state.degraded_reason
        return ""


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
