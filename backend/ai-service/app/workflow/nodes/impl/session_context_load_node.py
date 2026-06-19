"""会话上下文装载节点。

Phase 13 增强：在会话开始时检查 Redis 中是否有待处理的 Gating 审批结果
（用户批准的或拒绝的），并将其注入到 mcp_tool_state 的 Gating 字段中，
供下游上下文治理节点和主 Chat LLM 节点使用。
"""

from __future__ import annotations

from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.llm.context_manager import count_tokens
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import (
    CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED,
    CHAT_WORKFLOW_CONTEXT_WINDOW_READY,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import format_recent_history, split_key_facts


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
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.RUNNING),
        )

        if not self.dependencies.redis_repo:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            state.session_state.token_budget_total = 0
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.SKIPPED,
                display_text="",
                is_visible=False,
                is_terminal=True,
            )
            return state
        try:
            summary, history = await self.dependencies.redis_repo.get_context(state.runtime.session_id)
            state.session_state.recent_messages = [h.model_dump(mode="json") for h in history]
            state.session_state.short_summary = summary.core_summary
            state.session_state.key_facts = split_key_facts(summary.key_facts)
            state.session_state.memory_snippets = format_recent_history(history)
            state.session_state.token_budget_used = count_tokens(state.session_state.memory_snippets)
            state.session_state.token_budget_total = max(state.session_state.token_budget_used, 0)
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_READY

            # ============================================================
            # Phase 13 Gating：加载待处理的审批结果
            # 做什么：检查 Redis 中是否有待消费的审批结果（批准/拒绝）。
            #         如果有，将结果信息注入到 mcp_tool_state 的 Gating 字段中。
            # 为什么这样做：审批结果是异步发生的，需要在下次工作流中消费。
            #              下游 context_governance_node 会读取这些字段并
            #              注入到 chat/memory.j2 模板变量中。
            # 边界条件：
            #   - 没有待处理结果时静默跳过。
            #   - Redis 不可用时降级处理，不阻断主流程。
            # ============================================================
            try:
                from app.gating.snapshot import GatingSnapshotManager

                # 获取 Redis 客户端
                redis_client = getattr(self.dependencies, "redis_client", None)
                if not redis_client and self.dependencies.redis_repo:
                    redis_client = self.dependencies.redis_repo.redis_client

                if redis_client:
                    snapshot_manager = GatingSnapshotManager(redis_client)
                    pending_result = await snapshot_manager.load_pending_approval_result(
                        state.runtime.session_id
                    )

                    if pending_result:
                        result_type = pending_result.get("type", "")
                        tool_name = pending_result.get("tool_name", "")
                        tool_parameters = pending_result.get("tool_parameters", {})
                        user_feedback = pending_result.get("user_feedback", "")
                        rejection_info = pending_result.get("rejection_info", "")
                        tool_output = pending_result.get("tool_output", "")

                        if result_type == "rejected":
                            # 用户拒绝了工具调用
                            state.mcp_tool_state.gating_rejected = True
                            state.mcp_tool_state.gating_tool_name = tool_name
                            state.mcp_tool_state.gating_tool_parameters = tool_parameters
                            state.mcp_tool_state.gating_user_feedback = user_feedback
                            state.mcp_tool_state.gating_rejected_tool_info = rejection_info
                            state.mcp_tool_state.gating_mcp_intent = pending_result.get("mcp_intent", "")
                            state.mcp_tool_state.gating_risk_level = pending_result.get("risk_level", "L2")

                            logger.info(
                                f"[SessionContextLoad] 加载 Gating 拒绝结果"
                                f" session_id={state.runtime.session_id}"
                                f" tool={tool_name} feedback={user_feedback}"
                            )

                        elif result_type == "approved":
                            # 用户批准了工具调用，工具已执行
                            state.mcp_tool_state.gating_tool_name = tool_name
                            state.mcp_tool_state.gating_tool_parameters = tool_parameters
                            state.mcp_tool_state.gating_mcp_intent = pending_result.get("mcp_intent", "")

                            # 将工具执行结果注入到 execution_summary（复用现有字段）
                            state.mcp_tool_state.execution_summary = (
                                f"**已执行的工具:** {tool_name}\n\n"
                                f"**执行结果:**\n{tool_output}"
                            )

                            logger.info(
                                f"[SessionContextLoad] 加载 Gating 批准结果"
                                f" session_id={state.runtime.session_id}"
                                f" tool={tool_name} output_length={len(tool_output)}"
                            )

                        # 消费完成后清除待处理结果，防止重复消费
                        await snapshot_manager.clear_pending_approval_result(
                            state.runtime.session_id
                        )

                    else:
                        # 没有待处理的审批结果，正常继续
                        pass

            except ImportError:
                # GatingSnapshotManager 未导入，跳过（兼容旧版本）
                pass
            except Exception as gating_exc:
                logger.warning(
                    f"[SessionContextLoad] 加载 Gating 审批结果失败（降级处理）"
                    f" session_id={state.runtime.session_id} error={gating_exc}"
                )

            # ============================================================
            # Phase 13 Gating 加载完毕
            # ============================================================

            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.COMPLETED),
                is_terminal=True,
            )

        except Exception as exc:
            state.session_state.context_window_status = CHAT_WORKFLOW_CONTEXT_WINDOW_DEGRADED
            logger.warning(
                f"Redis 会话窗口装载失败，已降级为空窗口 trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc}"
            )
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.SESSION_CONTEXT_LOAD,
                status=ChatStatusState.ERROR,
                display_text=get_chat_status_text(ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.ERROR),
                is_terminal=True,
                error=str(exc),
            )
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
