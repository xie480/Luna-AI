"""
MCP Tool Execution Node — Phase 12 工具链循环执行核心工作流节点。

做什么：作为 LangGraph 的节点适配器，串联三 Agent 协作流程：
        初筛（输出有序工具链）→ 循环执行（遍历工具链：参数提取+执行+结果累积）
        → 意图对齐（聚合全部结果）。
为什么这样做：将 MCP 工具调用封装为独立的工作流节点，支持单工具和多工具链式调用，
            工具链中任一失败即终止整条链。
边界条件：
    - prompt_manager 不可用时直接降级跳过。
    - 无候选工具或 no_suitable_tool=True 时降级跳过。
    - 工具链中任一工具参数提取失败或执行失败即终止整条链。
    - 所有异常由本节点捕获并降级，不阻断主工作流。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.mcp_intent_alignment import MCPIntentAlignmentAgent
from app.agent.mcp_tool_calling import MCPToolCallingAgent
from app.agent.mcp_tool_screening import MCPToolScreeningAgent
from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.mcp.executor import execute_tool
from app.mcp.types import (
    IntentAlignmentResult,
    ToolChainPlan,
    ToolCallingResult,
)
from app.prompt.types import PromptCategory
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import (
    CHAT_WORKFLOW_MCP_TOOL_DEGRADED_REASON,
    CHAT_WORKFLOW_MCP_TOOL_NO_TOOL_REASON,
    ChatMCPAgentPhase,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatMCPToolState, ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import format_recent_history


class MCPToolExecutionNode(ChatWorkflowNode):
    """MCP Tool 执行节点（工具链循环执行版）。

    做什么：作为 LangGraph 的工作流节点，在输入重构节点判定需要工具调用时被激活。
            内部串联 Agent 1（初筛）→ Agent 2 循环执行（参数提取+执行）
            → Agent 3（意图对齐）的完整流程。
    为什么这样做：将 MCP 工具调用封装为独立节点，与长期记忆 RAG、知识库 RAG
                处于同等的条件分支地位，保持 DAG 结构的一致性。
    """

    def __init__(self, dependencies: WorkflowDependencies):
        """
        初始化 MCP Tool 执行节点。

        做什么：绑定节点类型和依赖容器。
        参数:
            dependencies: 工作流依赖容器，包含 prompt_manager、chat_status_publisher 等。
        """
        super().__init__(
            node_type=ChatWorkflowNodeType.MCP_TOOL_EXECUTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        LangGraph 节点调用入口。

        做什么：接收 LangGraph 传递的字典状态，通过 run_with_observation
                包装执行 _handle 方法。
        参数:
            state: LangGraph 传递的字典状态。
        返回:
            dict: LangGraph 可传播的状态字典。
        """
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        """
        节点核心处理逻辑。

        做什么：串联 Agent 1（初筛）→ Agent 2 循环执行（遍历工具链）
                → Agent 3（意图对齐）的完整流程。
        参数:
            state: 当前工作流类型化状态。
        返回:
            ChatWorkflowState: 更新后的工作流状态。
        """
        # 标记条件进入
        state.mcp_tool_state.entered_by_condition = True
        state.mcp_tool_state.condition_reason = "输入重构判定需要工具调用"

        # 发布 RUNNING 状态
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.MCP_TOOL_EXECUTION,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.MCP_TOOL_EXECUTION, ChatStatusState.RUNNING
            ),
        )

        prompt_manager = self.dependencies.prompt_manager

        # Prompt 管理器不可用时降级
        if not prompt_manager:
            return self._degrade_and_skip(state, "Prompt 管理器不可用")

        try:
            # ============================================================
            # Agent 1：工具初筛 → 输出有序 ToolChain
            # ============================================================
            state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.SCREENING.value

            # 获取 MCP PG 仓库引用（如果依赖容器中可用）
            mcp_pg_repo = getattr(self.dependencies, 'mcp_pg_repo', None)

            chain_plan: ToolChainPlan = await MCPToolScreeningAgent().screen(
                trace_id=state.runtime.trace_id,
                user_input=state.input_payload.raw_user_message,
                mcp_judgment=state.route_state.mcp_judgment_json or {},
                prompt_manager=prompt_manager,
                mcp_pg_repo=mcp_pg_repo,
            )
            # 将 Agent 1 的结果写入状态（序列化为 JSON）
            state.mcp_tool_state.screening_result = chain_plan.model_dump(mode="json")

            # 无合适工具时降级跳过
            if chain_plan.no_suitable_tool or not chain_plan.tool_chain:
                return self._degrade_and_skip(
                    state,
                    chain_plan.reasoning or CHAT_WORKFLOW_MCP_TOOL_NO_TOOL_REASON,
                )

            # ============================================================
            # Agent 2 循环执行引擎：遍历工具链逐轮执行
            # ============================================================
            state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.CALLING_LOOP.value

            # 格式化近期对话片段供 Agent 2 使用
            memory_snippets = format_recent_history(state.session_state.recent_messages)

            # 累积工具执行结果的数组
            tool_results: list[dict[str, Any]] = []
            # 前序工具结果，第 1 轮为空字符串，后续轮由上层节点注入
            previous_result: str = ""
            chain_aborted = False
            chain_error = ""

            # 按工具链顺序逐轮遍历
            for step_index, step in enumerate(chain_plan.tool_chain):
                state.mcp_tool_state.agent_phase = f"{ChatMCPAgentPhase.CALLING.value}_{step_index}"

                # ----- ① Agent 2：参数提取（第 2+ 轮注入前序结果）-----
                calling_agent = MCPToolCallingAgent()
                calling_result: ToolCallingResult = (
                    await calling_agent.extract_parameters(
                        trace_id=state.runtime.trace_id,
                        tool_name=step.tool_name,
                        user_input=state.input_payload.raw_user_message,
                        memory_snippets=memory_snippets,
                        core_summary=state.session_state.short_summary,
                        key_facts=state.session_state.key_facts,
                        prompt_manager=prompt_manager,
                        previous_tool_result=previous_result,
                    )
                )
                # 每轮的参数提取结果写入状态
                state.mcp_tool_state.calling_results.append(
                    calling_result.model_dump(mode="json")
                )

                # 参数提取失败：终止工具链
                if calling_result.call_parameters_failed:
                    chain_aborted = True
                    chain_error = (
                        f"工具链中 '{step.tool_name}' 参数提取失败: "
                        f"{calling_result.failure_reason}"
                    )
                    break

                # ----- ② 工具执行 -----
                state.mcp_tool_state.agent_phase = f"{ChatMCPAgentPhase.EXECUTION.value}_{step_index}"
                exec_result = await execute_tool(
                    tool_name=step.tool_name,
                    parameters=calling_result.parameters,
                    trace_id=state.runtime.trace_id,
                )

                # 工具执行失败：终止工具链
                if not exec_result.success:
                    chain_aborted = True
                    chain_error = (
                        f"工具链中 '{step.tool_name}' 执行失败: "
                        f"{exec_result.error_message}"
                    )
                    break

                # ----- ③ 格式化并累积结果 -----
                tool_results.append({
                    "tool_name": step.tool_name,
                    "execution_id": exec_result.execution_id,
                    "output_text": exec_result.output_text,
                    "latency_ms": exec_result.latency_ms,
                })
                # 更新前序结果，供下一轮使用
                previous_result = exec_result.output_text

            # 更新状态：最后一次执行信息
            if tool_results:
                last = tool_results[-1]
                state.mcp_tool_state.executed_tool_name = last["tool_name"]
                state.mcp_tool_state.execution_id = last["execution_id"]
                state.mcp_tool_state.output_text = last["output_text"]
                state.mcp_tool_state.latency_ms = last["latency_ms"]

            # 工具链终止：记录错误并降级
            if chain_aborted:
                state.mcp_tool_state.tool_results = tool_results
                state.mcp_tool_state.chain_aborted = True
                state.mcp_tool_state.chain_error = chain_error
                return self._degrade_and_skip(state, chain_error)

            # 工具链全部执行完成
            state.mcp_tool_state.tool_results = tool_results
            state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.CHAIN_COMPLETED.value

            # ============================================================
            # Agent 3：意图对齐（聚合全部工具结果）
            # ============================================================
            state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.ALIGNMENT.value

            # 将所有工具的原始输出聚合为一个文本
            aggregated_raw_output = "\n---\n".join(
                f"[{r['tool_name']}]:\n{r['output_text']}"
                for r in tool_results
            )
            aggregated_tool_names = ", ".join(
                r["tool_name"] for r in tool_results
            )

            alignment_agent = MCPIntentAlignmentAgent()
            alignment_result: IntentAlignmentResult = (
                await alignment_agent.align(
                    trace_id=state.runtime.trace_id,
                    user_input=state.input_payload.raw_user_message,
                    intent_summary=state.route_state.user_intent_summary,
                    tool_name=aggregated_tool_names,
                    tool_raw_output=aggregated_raw_output,
                    tool_latency_ms=sum(
                        r["latency_ms"] for r in tool_results
                    ),
                    tool_risk_level="L0",
                    prompt_manager=prompt_manager,
                )
            )
            # Agent 3 的结果写入状态
            state.mcp_tool_state.alignment_result = (
                alignment_result.model_dump(mode="json")
            )
            state.mcp_tool_state.calibrated_output = (
                alignment_result.calibrated_output
            )
            state.mcp_tool_state.quality_issue = alignment_result.quality_issue
            state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.COMPLETED.value

            # 发布完成状态
            await self._publish_chat_status(
                state=state,
                stage=ChatStatusStage.MCP_TOOL_EXECUTION,
                status=ChatStatusState.COMPLETED,
                display_text=get_chat_status_text(
                    ChatStatusStage.MCP_TOOL_EXECUTION,
                    ChatStatusState.COMPLETED,
                ),
                is_terminal=True,
            )

        except Exception as exc:
            # 所有未被内部捕获的异常统一降级
            logger.warning(
                f"MCP 工具执行节点异常降级 "
                f"trace_id={state.runtime.trace_id} "
                f"session_id={state.runtime.session_id} error={exc!s}"
            )
            return self._degrade_and_skip(
                state, f"MCP 节点异常: {exc!s}"
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
        """
        发布 Chat 状态事件的辅助方法。

        做什么：通过 ChatStatusPublisher 发布指定阶段和状态的 Chat 状态事件。
        为什么这样做：输入重构节点和其他节点均使用此模式，保持接口一致性。
        参数:
            state: 当前工作流状态。
            stage: Chat 主链路执行阶段。
            status: 阶段执行状态。
            display_text: 展示给前端的拟人化文本。
            is_visible: 状态是否对前端可见。
            is_terminal: 是否为终态。
            error: 错误信息（可选）。
        """
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

    def _degrade_and_skip(
        self, state: ChatWorkflowState, reason: str
    ) -> ChatWorkflowState:
        """
        降级标记并发布跳过状态。

        做什么：将 MCP 节点标记为降级状态，记录降级原因，
                发布 SKIPPED 状态事件（不可见），然后跳过。
        参数:
            state: 当前工作流状态。
            reason: 降级原因说明。
        返回:
            ChatWorkflowState: 标记降级后的状态。
        """
        state.mcp_tool_state.degraded = True
        state.mcp_tool_state.degraded_reason = reason
        state.mcp_tool_state.agent_phase = ChatMCPAgentPhase.DEGRADED.value

        # 发布 SKIPPED 状态（不可见，不阻塞前端）
        # 注意：此处不 await，因为 ChatWorkflowNode.run_with_observation
        # 中的异常捕获机制可能会在 publish 失败时误报节点失败。
        # 降级不是失败，不应阻断主链路。
        try:
            publisher: ChatStatusPublisher | None = (
                self.dependencies.chat_status_publisher
            )
            if publisher:
                asyncio.create_task(
                    publisher.publish(
                        trace_id=state.runtime.trace_id,
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        stage=ChatStatusStage.MCP_TOOL_EXECUTION,
                        state=ChatStatusState.SKIPPED,
                        display_text="",
                        is_visible=False,
                        is_terminal=True,
                    )
                )
        except Exception:
            pass

        return state
