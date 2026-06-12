"""
MCP Skill 执行节点 — Skill 三阶段 Agent 核心工作流节点（v3.0）。

做什么：作为 LangGraph 的节点适配器，串联三阶段 Agent 流程：
        Agent 1（Skill 初筛）→ Agent 2（Skill 加载·生成执行计划）
        → Agent 3（Skill 执行·含退回与终止）。
        本节点替换原有的 MCPToolExecutionNode。
为什么这样做：将"工具调用"升级为"技能调用"，通过三阶段分层决策
             实现更灵活的能力编排。引入退回和终止机制保证容错。
v3.0 变更：
    - 注入变量从 raw_user_message 改为 mcp_intent（MCP 前置节点提炼的意图文本）
    - execution_plan 的 state 结构变为单工具单资源（tool/resource 为字符串非数组）
    - 移除 execution_order，states 字典 key 顺序即执行顺序
    - 主循环各阶段细化 display_text（集中管理，使用 get_chat_status_text 获取）
    - 步长超限触发退回重试而非直接失败
边界条件：
    - prompt_manager 不可用时直接降级跳过。
    - 无候选 Skill 或 no_suitable_skill=True 时降级跳过。
    - 退回次数超过上限时触发最终失败。
    - 所有异常由本节点捕获并降级，不阻断主工作流。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.mcp_resource_sub_agent import MCPResourceSubAgent
from app.agent.mcp_skill_execution import MCPSkillExecutionAgent
from app.agent.mcp_skill_finalizer import (
    is_step_count_exceeded,
    should_trigger_final_fail,
)
from app.agent.mcp_skill_loading import MCPSkillLoadingAgent
from app.agent.mcp_skill_screening import MCPSkillScreeningAgent
from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import (
    format_execution_start,
    format_step_progress,
    get_chat_status_text,
)
from app.logger import logger
from app.mcp.executor import execute_tool
from app.mcp.skill_registry import SkillRegistry
from app.mcp.skill_types import (
    ExecutionPlan,
    FallbackState,
    FinalFailState,
    ResourceLoadResult,
    SkillAgentPhase,
    SkillChainPlan,
)
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.constants import (
    CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
    ChatWorkflowNodeType,
)
from app.workflow.context import ChatWorkflowState
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.nodes.dependencies import WorkflowDependencies
from app.workflow.nodes.helpers import first_reason


class MCPSkillExecutionNode(ChatWorkflowNode):
    """MCP Skill 执行节点（三阶段 Agent + 退回与终止机制，v3.0 单步 state 结构）。"""

    def __init__(self, dependencies: WorkflowDependencies):
        super().__init__(
            node_type=ChatWorkflowNodeType.MCP_SKILL_EXECUTION,
            event_publisher=dependencies.event_publisher,
        )
        self.dependencies = dependencies

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.run_with_observation(state, self._handle)

    async def _handle(self, state: ChatWorkflowState) -> ChatWorkflowState:
        # 标记条件进入
        state.mcp_tool_state.entered_by_condition = True
        state.mcp_tool_state.condition_reason = first_reason(
            state.route_state.route_reasons,
            CHAT_WORKFLOW_NO_SKILL_ROUTE_REASON,
        )

        # 获取 MCP 意图文本（来自 MCP 前置判断节点）
        mcp_intent = state.route_state.mcp_intent or state.input_payload.raw_user_message

        # 初始化状态
        state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_SCREENING.value
        fallback_count = 0
        step_count = 0
        all_tool_results: list[dict[str, Any]] = []
        last_fallback_state: FallbackState | None = None

        prompt_manager = self.dependencies.prompt_manager
        if not prompt_manager:
            return self._degrade_and_skip(state, "Prompt 管理器不可用")

        # ============================================================
        # 发布 RUNNING 状态（初筛阶段）
        # 使用集中管理的 display_text
        # ============================================================
        await self._publish_chat_status(
            state=state,
            stage=ChatStatusStage.MCP_SKILL_SCREENING,
            status=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.MCP_SKILL_SCREENING, ChatStatusState.RUNNING
            ),
        )

        # ============================================================
        # 主循环：Agent 1（初筛）→ Agent 2（加载）→ Agent 3（执行）→ 检查退回
        # ============================================================
        while True:
            try:
                # ============================================================
                # Agent 1：Skill 初筛
                # ============================================================
                state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_SCREENING.value
                skill_judgment = state.route_state.skill_judgment_json or {}

                # 如果有退回上下文，注入到 skill_judgment
                if last_fallback_state:
                    skill_judgment["fallback_context"] = {
                        "execution_snapshot": last_fallback_state.execution_snapshot,
                        "fallback_count": fallback_count,
                    }

                chain_plan: SkillChainPlan = await MCPSkillScreeningAgent().screen(
                    trace_id=state.runtime.trace_id,
                    mcp_intent=mcp_intent,
                    skill_judgment=skill_judgment,
                    prompt_manager=prompt_manager,
                )
                state.mcp_tool_state.screening_result = chain_plan.model_dump(mode="json")

                # 无合适 Skill 时降级跳过
                if chain_plan.no_suitable_skill or not chain_plan.selected_skill_ids:
                    logger.info(
                        "[MCP Skill Execution] No suitable skill found.",
                        extra={
                            "trace_id": state.runtime.trace_id,
                            "mcp_intent": mcp_intent,
                            "skill_judgment": skill_judgment,
                        },
                    )
                    return self._degrade_and_skip(
                        state,
                        chain_plan.reasoning or "MCP Agent 判定无需调用技能",
                    )

                # ============================================================
                # Agent 2：Skill 加载 → 生成执行计划
                # ============================================================
                state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_LOADING.value

                await self._publish_chat_status(
                    state=state,
                    stage=ChatStatusStage.MCP_SKILL_LOADING,
                    status=ChatStatusState.RUNNING,
                    display_text=get_chat_status_text(
                        ChatStatusStage.MCP_SKILL_LOADING, ChatStatusState.RUNNING
                    ),
                )

                execution_plan: ExecutionPlan = await MCPSkillLoadingAgent().load(
                    trace_id=state.runtime.trace_id,
                    skill_ids=chain_plan.selected_skill_ids,
                    mcp_intent=mcp_intent,
                    prompt_manager=prompt_manager,
                )

                # 空计划时降级跳过
                if not execution_plan.states:
                    return self._degrade_and_skip(
                        state,
                        f"Skill 加载失败: {execution_plan.reasoning}",
                    )

                state.mcp_tool_state.execution_plan = execution_plan.model_dump(mode="json")

                # v3.0：由业务代码统计 state 数量得到总步数
                state_count = len(execution_plan.states)
                step_count += state_count

                # 检查步长是否超限，超限则触发退回
                if is_step_count_exceeded(step_count):
                    logger.info(
                        f"MCP Skill 步长超限 trace_id={state.runtime.trace_id} "
                        f"step_count={step_count} fallback_count={fallback_count}，触发退回"
                    )
                    # 步长超限触发退回（不直接最终失败）
                    # 构造一个空的执行快照，表示当前计划超出步长
                    empty_snapshot = {}
                    for state_key, state_val in execution_plan.states.items():
                        empty_snapshot[state_key] = {
                            "skill": state_val.skill,
                            "tool": state_val.tool,
                            "resource": state_val.resource,
                            "goal": state_val.goal,
                            "status": "未执行（步长超限）",
                            "result": "",
                        }
                    last_fallback_state = FallbackState(
                        execution_snapshot=empty_snapshot,
                    )
                    fallback_count += 1

                    # 检查最终失败
                    final_fail = should_trigger_final_fail(
                        step_count=step_count,
                        fallback_count=fallback_count,
                        tool_results=all_tool_results,
                        execution_plan=execution_plan.model_dump(mode="json"),
                    )
                    if final_fail:
                        return self._handle_final_fail(state, final_fail)
                    continue  # 退回至 Agent 1

                # ============================================================
                # Agent 3：Skill 执行
                # ============================================================
                state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_RESOURCE_LOADING.value

                await self._publish_chat_status(
                    state=state,
                    stage=ChatStatusStage.MCP_SKILL_RESOURCE_LOADING,
                    status=ChatStatusState.RUNNING,
                    display_text=get_chat_status_text(
                        ChatStatusStage.MCP_SKILL_RESOURCE_LOADING, ChatStatusState.RUNNING
                    ),
                )

                # Step 3.1：并行加载所有 state 中的 Resources
                resource_results: list[ResourceLoadResult] = []
                sub_agent = MCPResourceSubAgent()
                load_tasks = []
                resource_to_state_map: dict[str, str] = {}  # resource_name -> state_key

                registry = SkillRegistry()
                for state_key, state_val in execution_plan.states.items():
                    # 如果此 state 有资源需要加载
                    if not state_val.resource:
                        continue
                    # 通过技能名称查找对应的 skill detail
                    detail = None
                    for sid in chain_plan.selected_skill_ids:
                        d = registry.get_skill_detail(sid)
                        if d and d.name == state_val.skill:
                            detail = d
                            break
                    if not detail:
                        continue

                    resource_def = next(
                        (r for r in detail.resources if r["name"] == state_val.resource),
                        None,
                    )
                    if resource_def and resource_def.get("resource_type") == "file":
                        load_tasks.append(
                            sub_agent.load_resource(
                                trace_id=state.runtime.trace_id,
                                resource_def=resource_def,
                                load_purpose=f"为技能 '{state_val.skill}' 的 state '{state_key}' 加载资源: {state_val.goal}",
                                prompt_manager=prompt_manager,
                            )
                        )
                        resource_to_state_map[state_val.resource] = state_key

                # 并行执行所有资源加载
                if load_tasks:
                    resource_results = await asyncio.gather(*load_tasks)

                state.mcp_tool_state.resource_results = [
                    r.model_dump(mode="json") for r in resource_results
                ]

                # 构建资源上下文映射
                resource_context_map: dict[str, str] = {}
                for rr in resource_results:
                    if rr.success:
                        resource_context_map[rr.resource_name] = rr.extracted_info

                # Step 3.2：按 state 字典顺序执行每个 state 中的 Tool
                state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_EXECUTION.value

                # 使用集中管理的执行开始文案
                total_states = len(execution_plan.states)
                await self._publish_chat_status(
                    state=state,
                    stage=ChatStatusStage.MCP_SKILL_TOOL_EXECUTING,
                    status=ChatStatusState.RUNNING,
                    display_text=format_execution_start(total_states),
                )

                tool_results: list[dict[str, Any]] = []
                exec_agent = MCPSkillExecutionAgent()

                # v3.0：按排序后的 state_key 顺序执行
                state_keys = sorted(execution_plan.states.keys())
                for idx, state_key in enumerate(state_keys):
                    state_val = execution_plan.states.get(state_key)
                    if not state_val:
                        continue

                    # 如果此 state 有工具需要执行
                    if not state_val.tool:
                        continue

                    # 使用集中管理的步骤进度文案
                    await self._publish_chat_status(
                        state=state,
                        stage=ChatStatusStage.MCP_SKILL_TOOL_EXECUTING,
                        status=ChatStatusState.RUNNING,
                        display_text=format_step_progress(
                            current_step=idx + 1,
                            total_steps=total_states,
                            step_goal=state_val.goal,
                        ),
                    )

                    # Agent 3 判断是否可以继续 + 提取参数
                    step_result = await exec_agent.execute_step(
                        trace_id=state.runtime.trace_id,
                        step_name=state_val.tool,
                        step_goal=state_val.goal,
                        execution_plan=execution_plan,
                        tool_results=tool_results,
                        resource_context=resource_context_map,
                        prompt_manager=prompt_manager,
                        mcp_intent=mcp_intent,
                    )

                    if step_result.get("can_proceed", False):
                        # 可以继续：使用 LLM 提取的 tool_parameters 执行工具
                        calling_result = await self._execute_single_tool(
                            trace_id=state.runtime.trace_id,
                            tool_name=state_val.tool,
                            tool_parameters=step_result.get("tool_parameters", {}),
                        )
                        tool_results.append({
                            "tool_name": state_val.tool,
                            "success": not calling_result.get("failed", False),
                            "output_text": calling_result.get("output", ""),
                            "error_message": calling_result.get("error", ""),
                            "resource_context_injected": step_result.get("resource_context_injected", []),
                            "latency_ms": calling_result.get("latency_ms", 0),
                            "can_proceed": True,
                        })
                    else:
                        # 无法继续：记录退回原因
                        tool_results.append({
                            "tool_name": state_val.tool,
                            "success": False,
                            "output_text": "",
                            "error_message": step_result.get("fallback_reason", ""),
                            "resource_context_injected": step_result.get("resource_context_injected", []),
                            "latency_ms": step_result.get("latency_ms", 0),
                            "can_proceed": False,
                            "fallback_reason": step_result.get("fallback_reason", ""),
                        })

                all_tool_results.extend(tool_results)
                state.mcp_tool_state.tool_results = all_tool_results

                # ============================================================
                # 检查是否需要退回
                # ============================================================
                need_fallback = self._evaluate_need_fallback(
                    tool_results=tool_results,
                    resource_results=resource_results,
                )

                if not need_fallback:
                    # 执行成功，退出循环
                    state.mcp_tool_state.agent_phase = SkillAgentPhase.COMPLETED.value

                    await self._publish_chat_status(
                        state=state,
                        stage=ChatStatusStage.MCP_SKILL_EXECUTION,
                        status=ChatStatusState.COMPLETED,
                        display_text=get_chat_status_text(
                            ChatStatusStage.MCP_SKILL_EXECUTION, ChatStatusState.COMPLETED
                        ),
                        is_terminal=True,
                    )
                    return state

                # 需要退回
                fallback_count += 1
                state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_FALLBACK.value

                await self._publish_chat_status(
                    state=state,
                    stage=ChatStatusStage.MCP_SKILL_FALLBACK,
                    status=ChatStatusState.RUNNING,
                    display_text=get_chat_status_text(
                        ChatStatusStage.MCP_SKILL_FALLBACK, ChatStatusState.RUNNING
                    ),
                )

                # 提取执行快照（v3.0 格式：tool/resource 为字符串）
                execution_snapshot = await sub_agent.extract_fallback_info(
                    trace_id=state.runtime.trace_id,
                    execution_plan=execution_plan.model_dump(mode="json"),
                    tool_results=tool_results,
                    resource_results=resource_results,
                    prompt_manager=prompt_manager,
                )
                last_fallback_state = FallbackState(
                    execution_snapshot=execution_snapshot,
                )

                # 检查是否需要触发最终失败
                final_fail = should_trigger_final_fail(
                    step_count=step_count,
                    fallback_count=fallback_count,
                    tool_results=all_tool_results,
                    execution_plan=execution_plan.model_dump(mode="json"),
                )
                if final_fail:
                    return self._handle_final_fail(state, final_fail)

                # 继续循环（退回至 Agent 1）

            except Exception as exc:
                logger.warning(
                    f"MCP Skill 执行节点异常降级 "
                    f"trace_id={state.runtime.trace_id} "
                    f"session_id={state.runtime.session_id} error={exc!s}"
                )
                return self._degrade_and_skip(state, f"MCP 节点异常: {exc!s}")

    async def _execute_single_tool(
        self,
        trace_id: str,
        tool_name: str,
        tool_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """执行单个工具（使用 LLM 已提取的参数）。

        做什么：使用 Agent 3 LLM 已提取的 tool_parameters，直接通过
                execute_tool 执行工具调用。无需再经过 MCPToolCallingAgent。
        参数:
            trace_id: 全链路追踪 ID。
            tool_name: 工具名称。
            tool_parameters: Agent 3 LLM 提取的工具调用参数。
        返回:
            dict: 包含 failed、error、output、latency_ms。
        """
        import time
        started_at = time.monotonic()

        # 直接使用 Agent 3 提取的参数执行工具
        exec_result = await execute_tool(
            tool_name=tool_name,
            parameters=tool_parameters,
            trace_id=trace_id,
        )

        return {
            "failed": not exec_result.success,
            "error": exec_result.error_message if not exec_result.success else "",
            "output": exec_result.output_text if exec_result.success else "",
            "latency_ms": exec_result.latency_ms,
        }

    def _evaluate_need_fallback(
        self,
        tool_results: list[dict[str, Any]],
        resource_results: list[ResourceLoadResult],
    ) -> bool:
        """评估是否需要退回。

        做什么：检查当前 Skill 计划执行后是否仍有未满足的需求。
                如果所有工具的 can_proceed 都为 true 且执行成功，认为不需要退回。
        参数:
            tool_results: 已执行的工具结果列表。
            resource_results: 已加载的资源结果列表。
        返回:
            bool: True 表示需要退回，False 表示无需退回。
        """
        # 检查是否有工具返回 can_proceed=false
        for r in tool_results:
            if not r.get("can_proceed", True):
                return True
            if not r.get("success", False):
                return True

        # 如果所有工具都执行成功，不需要退回
        if tool_results and all(r.get("success") for r in tool_results):
            return False

        # 如果没有工具执行但有资源加载成功，也认为不需要退回
        if not tool_results and resource_results:
            return False

        return True

    def _handle_final_fail(
        self,
        state: ChatWorkflowState,
        final_fail: FinalFailState,
    ) -> ChatWorkflowState:
        """处理最终失败：跳过至主 Chat LLM。

        做什么：将最终失败信息注入状态，发布 SKIPPED 事件，
                让下游主 Chat LLM 节点根据失败理由向用户说明。
        """
        state.mcp_tool_state.agent_phase = SkillAgentPhase.SKILL_FINAL_FAIL.value
        state.mcp_tool_state.degraded = True
        state.mcp_tool_state.degraded_reason = final_fail.failure_reason
        state.mcp_tool_state.final_fail_state = final_fail.model_dump(mode="json")

        # 发布 SKIPPED 状态
        try:
            publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
            if publisher:
                _ = asyncio.create_task(
                    publisher.publish(
                        trace_id=state.runtime.trace_id,
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        stage=ChatStatusStage.MCP_SKILL_EXECUTION,
                        state=ChatStatusState.SKIPPED,
                        display_text="",
                        is_visible=False,
                        is_terminal=True,
                    )
                )
        except Exception:
            pass

        return state

    def _degrade_and_skip(
        self, state: ChatWorkflowState, reason: str
    ) -> ChatWorkflowState:
        """降级标记并发布跳过状态。"""
        state.mcp_tool_state.degraded = True
        state.mcp_tool_state.degraded_reason = reason
        state.mcp_tool_state.agent_phase = SkillAgentPhase.DEGRADED.value

        try:
            publisher: ChatStatusPublisher | None = self.dependencies.chat_status_publisher
            if publisher:
                _ = asyncio.create_task(
                    publisher.publish(
                        trace_id=state.runtime.trace_id,
                        session_id=state.runtime.session_id,
                        message_id=state.generation_state.assistant_message_id,
                        stage=ChatStatusStage.MCP_SKILL_EXECUTION,
                        state=ChatStatusState.SKIPPED,
                        display_text="",
                        is_visible=False,
                        is_terminal=True,
                    )
                )
        except Exception:
            pass

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
        """发布 Chat 状态事件。"""
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
