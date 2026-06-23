"""Phase 9 DAG 引擎 — Plan + Cursor 子图工厂。

做什么：将原 DagEngine 单体引擎重构为 Plan + Cursor 子图工厂，
        包含 4 个独立 LangGraph 节点：Planner / Executor / Router / Summary。
为什么这样做：原 DagEngine.run() 内部使用 Python while 循环驱动 State 执行，
              整个 Plan 执行是一次不可分割的 LangGraph 节点调用，无法享受
              Checkpoint 断点恢复能力。重构后每个 State 执行都是独立的
              LangGraph 节点调用，天然享受 Checkpoint 断点恢复能力。

核心公式：动态 DAG = 固定 Graph（4 个节点）+ Plan（任务列表）+ Cursor（执行指针）
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.utils.snowflake import generate_string_id
from app.workflow.constants import DagSubGraphNodeName, DagWorkflowEventType
from app.workflow.context import ChatWorkflowState
from app.workflow.dag.budget import BudgetTracker
from app.workflow.dag.evaluation import StateResultCompressor
from app.workflow.dag.nodes.cursor_router import route_by_cursor_from_graph_state
from app.workflow.dag.nodes.plan_generation import PlanGenerationNode
from app.workflow.dag.nodes.plan_replan import PlanReplanNode
from app.workflow.dag.nodes.plan_summary import PlanResultSummaryNode
from app.workflow.dag.nodes.skill_screening import SkillScreeningNode
from app.workflow.dag.nodes.state_evaluation import StateEvaluationNode
from app.workflow.dag.nodes.step_executor import StepExecutor, StepRetryPolicy
from app.workflow.dag.nodes.step_merge import StepMergeNode
from app.workflow.dag.nodes.step_plan import StepPlanNode
from app.workflow.dag.types import (
    DagCursorRoute,
    DagEngineState,
    DagNodeStatus,
    DagNodeType,
    GlobalBudget,
    PlanSummaryResult,
    ReplanContext,
    StateBudget,
    StateEvaluationResult,
    StateRuntimeState,
)
from app.workflow.events import ChatWorkflowEventPublisher


# ===========================================================================
# 模块级工具函数（从原 DagEngine 类中提取，供各节点共享）
# ===========================================================================


async def _emit_dag_event(
    event_type: DagWorkflowEventType,
    trace_id: str,
    session_id: str,
    dag_state: DagEngineState,
    payload: dict[str, Any],
    event_publisher: ChatWorkflowEventPublisher | None,
) -> None:
    """发布 DAG 工作流事件到前端。

    做什么：将 DAG 生命周期事件通过 SSE 通道推送给前端 dagWorkflowStore。
    为什么这样做：前端 HolographicWorkflowSidebar 依赖 EVT_DAG_* 事件驱动 DAG 面板渲染。
    参数:
        event_type: DAG 事件类型枚举（如 EVT_DAG_PLAN_CREATED）。
        trace_id: 当前请求的追踪 ID。
        session_id: 会话 ID。
        dag_state: DAG 引擎全局状态（用于提取 interaction_id 等）。
        payload: 事件载荷字典，结构必须与前端 shared/types.ts 中对应接口一致。
        event_publisher: 事件发布器实例。
    边界条件：event_publisher 为空时静默跳过，不阻断主链路。
    异常行为：事件发布失败仅打印警告，不中断 DAG 引擎执行。
    """
    if not event_publisher:
        return
    try:
        # 直接通过 SSE 通道发布，避免 ChatWorkflowEventType 类型约束
        from app.api.sse import sse_manager
        await sse_manager.publish({
            "type": event_type.value,
            "trace_id": trace_id,
            "payload": payload,
        })
    except Exception as exc:
        logger.warning(f"DAG 事件发布失败: type={event_type.value}, error={exc}")


def _build_state_context(
    dag_state: DagEngineState,
    current_state: Any,
    budget_tracker: BudgetTracker,
    session_id: str,
    memory_manager: Any,
    rag_orchestrator: Any,
    mcp_tool_registry: Any,
) -> dict[str, Any]:
    """构建 State 执行上下文。

    做什么：将 DAG 引擎的状态注入到 state_context 中，
           供各原子节点执行时读取。
    为什么这样做：原子节点（StepExecutor 等）需要访问 session_id、
                  memory_manager 等运行时依赖，通过 state_context 字典传递。
    参数:
        dag_state: DAG 引擎全局状态。
        current_state: 当前执行的 OverallState 定义。
        budget_tracker: 预算追踪器。
        session_id: 会话 ID。
        memory_manager: 记忆管理器实例。
        rag_orchestrator: RAG 检索编排器实例。
        mcp_tool_registry: MCP 工具注册中心实例。
    返回:
        dict: state_context 字典，供原子节点使用。
    """
    return {
        "session_id": session_id,
        "user_id": dag_state.workflow_state.get("runtime", {}).get(
            "user_id", "local_default_user"
        ),
        "trace_id": dag_state.plan.trace_id,
        "state_goal": current_state.goal,
        "state_intent": current_state.intent,
        "skill_registry": mcp_tool_registry,
        "memory_manager": memory_manager,
        "rag_orchestrator": rag_orchestrator,
        "disambiguated_text": dag_state.disambiguated_text,
        "session_context": dag_state.session_context,
        "user_profile": dag_state.user_profile,
        "memory_context": dag_state.memory_context,
        "partitioned_outputs": {},
        "current_step_context": {},
        "steps_total": 0,
    }


def _build_replan_context(
    dag_state: DagEngineState,
    current_state: Any,
    state_runtime: StateRuntimeState,
    eval_result: StateEvaluationResult,
    compressed_result: str,
) -> ReplanContext:
    """构建 Plan 重构上下文。

    做什么：从 DagEngineState 中提取已完成 State 摘要和待修改的后续 State 列表，
           组装为 PlanReplanNode 所需的 ReplanContext。
    为什么这样做：Plan 重构节点需要知道哪些 State 已完成、哪些待修改，
                  以及失败 State 的评估结果，才能合理调整 Plan。
    参数:
        dag_state: DAG 引擎全局状态。
        current_state: 当前失败的 OverallState 定义。
        state_runtime: 当前 State 的运行时状态。
        eval_result: State 评估结果。
        compressed_result: 压缩后的 State 结果文本。
    返回:
        ReplanContext: Plan 重构上下文。
    """
    # 已完成 State 的摘要
    completed_states = []
    for sid, runtime_data in dag_state.state_runtimes.items():
        if runtime_data.get("status") == DagNodeStatus.SUCCEEDED.value:
            completed_states.append({
                "state_id": sid,
                "intent": runtime_data.get("intent", ""),
                "goal": runtime_data.get("goal", ""),
            })

    # 待修改的后续 State
    remaining_states = []
    for state_def in dag_state.plan.states[dag_state.cursor + 1:]:
        remaining_states.append({
            "state_id": state_def.state_id,
            "order_index": state_def.order_index,
            "intent": state_def.intent,
            "goal": state_def.goal,
        })

    return ReplanContext(
        failed_state_id=current_state.state_id,
        failed_state_goal=current_state.goal,
        failed_state_result=compressed_result,
        evaluation_reason=eval_result.evaluation_reason,
        gap_analysis=eval_result.gap_analysis,
        suggestion=eval_result.suggestion,
        completed_states=completed_states,
        remaining_states=remaining_states,
        global_objective=dag_state.global_objective,
    )


def _build_skill_screening_event_payload(
    dag_state: DagEngineState,
    current_state: Any,
    selected_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建 Skill 初筛事件载荷。

    做什么：将 Skill 初筛结果格式化为前端期望的事件载荷结构。
    为什么这样做：避免在多个节点中重复相同的格式化逻辑。
    """
    return {
        "plan_id": dag_state.plan.plan_id,
        "state_id": current_state.state_id,
        "selected_skills": [
            {
                "skill_name": s.get("skill_name", ""),
                "description": s.get("description", ""),
                "tool_names": s.get("tool_names", []),
                "capability_tags": s.get("capability_tags", []),
            }
            for s in (selected_skills if isinstance(selected_skills, list) else [])
        ],
    }


def _build_step_plan_event_payload(
    dag_state: DagEngineState,
    current_state: Any,
    steps: list[Any],
) -> dict[str, Any]:
    """构建 Step Plan 生成事件载荷。

    做什么：将 Step Plan 结果格式化为前端期望的事件载荷结构。
    为什么这样做：避免在多个节点中重复相同的格式化逻辑。
    """
    return {
        "plan_id": dag_state.plan.plan_id,
        "state_id": current_state.state_id,
        "steps": [
            {
                "step_id": s.step_id,
                "step_index": s.step_index,
                "description": s.description,
                "execution_mode": "parallel",
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "node_type": n.node_type.value if hasattr(n.node_type, 'value') else str(n.node_type),
                        "skill_name": n.skill_name,
                        "tool_name": n.tool_name,
                        "resource_name": n.resource_name,
                        "parameter_hint": n.parameter_hint,
                        "transform_instruction": n.transform_instruction,
                        "query_text": n.query_text,
                        "depends_on": n.depends_on,
                        "gating_required": n.gating_required,
                    }
                    for n in s.nodes
                ],
            }
            for s in steps
        ],
    }


# ===========================================================================
# 节点 1: DagPlannerNode — Plan 生成节点
# ===========================================================================


class DagPlannerNode:
    """Plan 生成节点 — LangGraph 子图节点。

    做什么：从 ChatWorkflowState 提取上下文，构建 DagEngineState，
           执行全局 Plan 生成，将结果写入 dag_state.dag_engine_state。
    为什么这样做：对应原 DagEngine.run() 中的 Phase 1 逻辑。
                  Plan 生成完成后，后续节点通过 dag_engine_state 读取 Plan。
    """

    def __init__(
        self,
        plan_generation: PlanGenerationNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化 Plan 生成节点。

        参数:
            plan_generation: Plan 生成子节点实例。
            chat_status_publisher: Chat 状态发布器。
            event_publisher: DAG 工作流事件发布器。
        """
        self.plan_generation = plan_generation
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行全局 Plan 生成。

        做什么：
        1. 从 ChatWorkflowState 提取上下文，构建 DagEngineState
        2. 调用 plan_generation.execute() 生成全局 Plan
        3. 发布 EVT_DAG_PLAN_CREATED 事件
        4. 将 DagEngineState 写回 ChatWorkflowState.dag_state.dag_engine_state

        返回:
            dict: 更新后的 ChatWorkflowState 图状态。
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 从 ChatWorkflowState 构建 DagEngineState
        dag_state = self._build_dag_state(chat_state)

        # 记录引擎启动时间，存入 workflow_state 供 Summarizer 计算耗时
        dag_state.workflow_state["dag_engine_started_at_ms"] = int(time.time() * 1000)

        # 发布引擎入口状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_ENGINE_ENTRY,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_ENGINE_ENTRY, ChatStatusState.RUNNING
            ),
            is_visible=True,
            is_terminal=False,
        )

        try:
            # ============================================================
            # Phase 1: 全局 Plan 生成
            # ============================================================
            dag_state = await self.plan_generation.execute(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
            )

            # 如果 Plan 为空，标记终止
            if not dag_state.plan.states:
                logger.warning(
                    f"[TraceID:{trace_id}] Plan 生成结果为空，跳过执行"
                )
                dag_state.terminated = True
                dag_state.termination_reason = "Plan 生成结果为空"

            # === 发布 DAG Plan 创建事件（前端 DAG 面板数据入口） ===
            if not dag_state.terminated:
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_PLAN_CREATED,
                    trace_id, session_id, dag_state,
                    {
                        "plan_id": dag_state.plan.plan_id,
                        "session_id": dag_state.plan.session_id,
                        "interaction_id": dag_state.workflow_state.get("runtime", {}).get("interaction_id", ""),
                        "assistant_message_id": dag_state.workflow_state.get("generation_state", {}).get("assistant_message_id", ""),
                        "global_objective": {
                            "overall_goal": dag_state.global_objective.overall_goal,
                            "success_criteria": dag_state.global_objective.success_criteria,
                            "output_format": dag_state.global_objective.output_format,
                            "constraints": dag_state.global_objective.constraints,
                        },
                        "states": [
                            {
                                "state_id": s.state_id,
                                "order_index": s.order_index,
                                "intent": s.intent,
                                "goal": s.goal,
                                "completion_criteria": [c.model_dump() for c in s.completion_criteria],
                                "depends_on": s.depends_on,
                                "required_skill_names": s.required_skill_names,
                            }
                            for s in dag_state.plan.states
                        ],
                        "planning_reason": dag_state.plan.original_intent or "",
                        "budget_consumed": {"tool_calls": 0},
                        "budget_limit": {"max_total_tool_calls": dag_state.plan.global_budget.max_total_tool_calls},
                    },
                    self.event_publisher,
                )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] Plan 生成异常: {exc}"
            )
            dag_state.terminated = True
            dag_state.termination_reason = f"Plan 生成异常: {exc}"

        # 将 DagEngineState 写回 ChatWorkflowState
        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
        return chat_state.as_graph_state()

    def _build_dag_state(self, chat_state: ChatWorkflowState) -> DagEngineState:
        """从 ChatWorkflowState 构建 DagEngineState。

        做什么：提取必要的上下文数据，构建 DAG 引擎的初始状态。
                包括从 SkillRegistry 单例中加载所有可用 Skill 的 Brief 列表，
                填充到 DagEngineState.skill_briefs，供 Plan 生成和 Skill 初筛使用。
        为什么这样做：DagEngineState 是 DAG 引擎的唯一状态容器，
                      需要在 Plan 生成前完成初始化。
        """
        # 从 SkillRegistry 单例获取所有可用 Skill 的 Brief 列表
        from app.mcp.skill_registry import SkillRegistry
        skill_briefs = SkillRegistry().get_skill_briefs()

        if skill_briefs:
            logger.info(
                f"[TraceID:{chat_state.runtime.trace_id}] "
                f"从 SkillRegistry 加载 skill_briefs: count={len(skill_briefs)}"
            )
        else:
            logger.warning(
                f"[TraceID:{chat_state.runtime.trace_id}] "
                f"SkillRegistry 中无可用 Skill，skill_briefs 为空"
            )

        return DagEngineState(
            disambiguated_text=chat_state.dag_state.disambiguated_text
                or chat_state.input_payload.raw_user_message,
            unresolved_pronouns=chat_state.dag_state.unresolved_pronouns,
            skill_briefs=skill_briefs,
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


# ===========================================================================
# 节点 2: DagStateExecutorNode — 单 State 执行节点
# ===========================================================================


class DagStateExecutorNode:
    """单个 State 执行节点 — LangGraph 子图节点。

    做什么：执行 dag_state.plan.states[cursor] 这一个 State，
           推进 cursor，发布 DAG 事件。
    为什么这样做：对应原 DagEngine.run() 的 while 循环体内部逻辑。
                  每次调用只处理一个 State，LangGraph 自动为每次调用生成 Checkpoint。
    """

    def __init__(
        self,
        skill_screening: SkillScreeningNode,
        step_plan: StepPlanNode,
        step_executor: StepExecutor,
        step_retry: StepRetryPolicy,
        step_merge: StepMergeNode,
        state_evaluation: StateEvaluationNode,
        state_compressor: StateResultCompressor,
        plan_replan: PlanReplanNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        memory_manager: Any = None,
        rag_orchestrator: Any = None,
        mcp_tool_registry: Any = None,
    ):
        """初始化 State 执行节点。

        参数:
            skill_screening: Skill 初筛子节点。
            step_plan: Step Plan 生成子节点。
            step_executor: Step 执行子节点。
            step_retry: Step 重试策略。
            step_merge: Step 合并子节点。
            state_evaluation: State 评估子节点。
            state_compressor: State 结果压缩器。
            plan_replan: Plan 重构子节点。
            chat_status_publisher: Chat 状态发布器。
            event_publisher: DAG 工作流事件发布器。
            memory_manager: 记忆管理器。
            rag_orchestrator: RAG 检索编排器。
            mcp_tool_registry: MCP 工具注册中心。
        """
        self.skill_screening = skill_screening
        self.step_plan = step_plan
        self.step_executor = step_executor
        self.step_retry = step_retry
        self.step_merge = step_merge
        self.state_evaluation = state_evaluation
        self.state_compressor = state_compressor
        self.plan_replan = plan_replan
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher
        self._memory_manager = memory_manager
        self._rag_orchestrator = rag_orchestrator
        self._mcp_tool_registry = mcp_tool_registry

    async def __call__(self, state: dict[str, Any]) -> Command:
        """LangGraph 节点入口 — 执行 plan.states[cursor] 这一个 State。

        做什么：
        1. 从 ChatWorkflowState 读取 DagEngineState（含 plan、cursor）
        2. current_state = plan.states[cursor]
        3. Skill 初筛 → Step Plan → 逐 Step 执行 → 合并 → State 评估
        4. 评估通过：cursor += 1, status = SUCCEEDED
           评估不通过：压缩 + 重构 Plan（首次）或标记终止（已达上限）
        5. 发布所有 DAG 事件（与当前完全一致）
        6. 返回 Command(goto="dag_cursor_router")

        返回:
            Command: 包含状态更新和路由跳转的 Command 对象。
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 反序列化 DagEngineState
        dag_engine_data = chat_state.dag_state.dag_engine_state
        if not dag_engine_data:
            logger.warning(
                f"[TraceID:{trace_id}] Executor: dag_engine_state 为空，跳过执行"
            )
            return Command(
                update={"dag_state": chat_state.dag_state.model_dump(mode="json")},
                goto=DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
            )

        dag_state = DagEngineState(**dag_engine_data)

        # 安全守卫：如果已终止或 cursor 越界，直接跳到 Router
        if dag_state.terminated or dag_state.cursor >= len(dag_state.plan.states):
            logger.info(
                f"[TraceID:{trace_id}] Executor: 已终止或无待执行 State，"
                f"terminated={dag_state.terminated}, "
                f"cursor={dag_state.cursor}, "
                f"states_count={len(dag_state.plan.states)}"
            )
            return Command(
                update={"dag_state": chat_state.dag_state.model_dump(mode="json")},
                goto=DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
            )

        current_state = dag_state.plan.states[dag_state.cursor]

        logger.info(
            f"[TraceID:{trace_id}] 开始执行 State: "
            f"cursor={dag_state.cursor}, "
            f"state_id={current_state.state_id}, "
            f"intent={current_state.intent}"
        )

        # 发布 State 执行开始状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_STATE_EXECUTION,
            state=ChatStatusState.RUNNING,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_STATE_EXECUTION,
                ChatStatusState.RUNNING,
            ),
            is_visible=True,
            is_terminal=False,
        )

        # === 发布 DAG State 启动事件 ===
        await _emit_dag_event(
            DagWorkflowEventType.EVT_DAG_STATE_STARTED,
            trace_id, session_id, dag_state,
            {
                "plan_id": dag_state.plan.plan_id,
                "state_id": current_state.state_id,
                "order_index": current_state.order_index,
                "goal": current_state.goal,
            },
            self.event_publisher,
        )

        # 初始化 State 运行时
        state_runtime = StateRuntimeState(
            state_id=current_state.state_id,
            status=DagNodeStatus.RUNNING,
            intent=current_state.intent,
            goal=current_state.goal,
        )

        # 从 DagEngineState 恢复全局预算消耗，创建 BudgetTracker
        budget_tracker = BudgetTracker(
            state_budget=StateBudget(),
            global_budget=dag_state.plan.global_budget,
            trace_id=trace_id,
        )
        budget_tracker.global_consumed = dag_state.budget_consumed.get("tool_calls", 0)

        # 构建 state_context
        state_context = _build_state_context(
            dag_state=dag_state,
            current_state=current_state,
            budget_tracker=budget_tracker,
            session_id=session_id,
            memory_manager=self._memory_manager,
            rag_orchestrator=self._rag_orchestrator,
            mcp_tool_registry=self._mcp_tool_registry,
        )

        try:
            # --- Skill 初筛 ---
            selected_skills = await self.skill_screening.execute(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
                state_goal=current_state.goal,
                state_intent=current_state.intent,
                completion_criteria=[
                    c.model_dump() for c in current_state.completion_criteria
                ],
            )
            state_runtime.selected_skills = selected_skills

            # === 发布 DAG Skill 初筛事件 ===
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_SKILL_SCREENING,
                trace_id, session_id, dag_state,
                _build_skill_screening_event_payload(dag_state, current_state, selected_skills),
                self.event_publisher,
            )

            # --- Step Plan 生成 ---
            try:
                steps = await self.step_plan.execute(
                    trace_id=trace_id,
                    session_id=session_id,
                    state_goal=current_state.goal,
                    state_intent=current_state.intent,
                    selected_skills=selected_skills,
                    state_context=state_context,
                )
                state_runtime.steps_total = len(steps)
                state_runtime.step_plan = [
                    s.model_dump() for s in steps
                ]

                # === 发布 DAG Step Plan 生成事件 ===
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_STEP_PLAN_GENERATED,
                    trace_id, session_id, dag_state,
                    _build_step_plan_event_payload(dag_state, current_state, steps),
                    self.event_publisher,
                )
            except Exception as e:
                logger.error(
                    f"[TraceID:{trace_id}] Step Plan 生成失败: {e}"
                )
                state_runtime.status = DagNodeStatus.FAILED
                state_runtime.error_messages.append(str(e))
                dag_state.state_runtimes[current_state.state_id] = (
                    state_runtime.model_dump()
                )
                dag_state.terminated = True
                dag_state.termination_reason = f"Step Plan 生成失败: {e}"
                dag_state.termination_state_id = current_state.state_id

                # 写回并跳转到 Router
                dag_state.budget_consumed["tool_calls"] = budget_tracker.global_consumed
                chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
                return Command(
                    update={"dag_state": chat_state.dag_state.model_dump(mode="json")},
                    goto=DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
                )

            # --- 逐 Step 执行 ---
            all_partitioned_outputs: dict[str, dict[str, Any]] = {}
            # 构建 node_id → node_def 映射，用于发射 NODE_STARTED/COMPLETED 事件
            node_def_map: dict[str, Any] = {}
            for step in steps:
                for n in step.nodes:
                    node_def_map[n.node_id] = n

            for step in steps:
                # 检查预算
                if budget_tracker.is_state_budget_exhausted():
                    logger.warning(
                        f"[TraceID:{trace_id}] State 预算耗尽，"
                        f"跳过剩余 Step"
                    )
                    state_runtime.budget_exhausted = True
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_BUDGET_EXHAUSTED,
                        trace_id, session_id, dag_state,
                        {
                            "plan_id": dag_state.plan.plan_id,
                            "level": "state",
                            "consumed": budget_tracker.global_consumed,
                            "limit": budget_tracker.global_limit,
                        },
                        self.event_publisher,
                    )
                    break

                if budget_tracker.is_global_budget_exhausted():
                    logger.warning(
                        f"[TraceID:{trace_id}] Plan 全局预算耗尽，"
                        f"终止引擎"
                    )
                    dag_state.terminated = True
                    dag_state.termination_reason = "Plan 全局预算耗尽"
                    dag_state.termination_state_id = current_state.state_id
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_BUDGET_EXHAUSTED,
                        trace_id, session_id, dag_state,
                        {
                            "plan_id": dag_state.plan.plan_id,
                            "level": "global",
                            "consumed": budget_tracker.global_consumed,
                            "limit": budget_tracker.global_limit,
                        },
                        self.event_publisher,
                    )
                    break

                # === 发射 Step 内所有节点的 NODE_STARTED 事件 ===
                for node_in_step in step.nodes:
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_NODE_STARTED,
                        trace_id, session_id, dag_state,
                        {
                            "plan_id": dag_state.plan.plan_id,
                            "state_id": current_state.state_id,
                            "step_id": step.step_id,
                            "node_id": node_in_step.node_id,
                            "node_type": node_in_step.node_type.value
                                if hasattr(node_in_step.node_type, 'value')
                                else str(node_in_step.node_type),
                        },
                        self.event_publisher,
                    )

                # 带重试执行 Step
                state_context["steps_total"] = len(steps)
                step_outputs, step_errors = await self.step_retry.execute_with_retry(
                    trace_id=trace_id,
                    step_def=step,
                    state_context=state_context,
                )

                if step_outputs:
                    all_partitioned_outputs.update(step_outputs)
                if step_errors:
                    state_runtime.error_messages.extend(step_errors)

                state_runtime.steps_completed += 1

                # 统计成功/失败节点并发射 NODE_COMPLETED 事件
                for nid, out in step_outputs.items():
                    success = out.get("success", True)
                    if success:
                        state_runtime.nodes_succeeded += 1
                    else:
                        state_runtime.nodes_failed += 1

                    # 每个工具执行节点消耗一次预算配额
                    node_def = node_def_map.get(nid)
                    if node_def and getattr(node_def, 'node_type', None) == DagNodeType.TOOL_EXECUTE:
                        budget_tracker.consume_tool_call()

                    # === 发射 NODE_COMPLETED 事件 ===
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_NODE_COMPLETED,
                        trace_id, session_id, dag_state,
                        {
                            "plan_id": dag_state.plan.plan_id,
                            "state_id": current_state.state_id,
                            "step_id": step.step_id,
                            "node_id": nid,
                            "node_type": node_def.node_type.value
                                if node_def and hasattr(node_def.node_type, 'value')
                                else (str(node_def.node_type) if node_def else "unknown"),
                            "success": success,
                            "outputs": {
                                k: v for k, v in out.items()
                                if k not in ("success", "error_message")
                            } if isinstance(out, dict) else {},
                            "error_message": out.get("error_message", "") if not success and isinstance(out, dict) else None,
                            "latency_ms": out.get("latency_ms", 0),
                            "retry_count": out.get("retry_count", 0),
                        },
                        self.event_publisher,
                    )

            if dag_state.terminated:
                # 预算耗尽导致终止，直接跳转到 Router
                dag_state.budget_consumed["tool_calls"] = budget_tracker.global_consumed
                chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
                return Command(
                    update={"dag_state": chat_state.dag_state.model_dump(mode="json")},
                    goto=DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
                )

            # Step 合并
            state_runtime.partitioned_outputs = all_partitioned_outputs
            merge_result = await self.step_merge.merge(
                trace_id=trace_id,
                session_id=session_id,
                partitioned_outputs=all_partitioned_outputs,
            )
            state_runtime.merged_output = merge_result.get("merged_output", {})

            # --- State 评估 ---
            eval_result = await self.state_evaluation.execute(
                trace_id=trace_id,
                session_id=session_id,
                state_goal=current_state.goal,
                state_intent=current_state.intent,
                completion_criteria=[
                    c.model_dump() for c in current_state.completion_criteria
                ],
                merged_output=state_runtime.merged_output,
                nodes_succeeded=state_runtime.nodes_succeeded,
                nodes_failed=state_runtime.nodes_failed,
            )

            state_runtime.evaluation_result = eval_result.model_dump()

            # === 发布 DAG State 评估事件 ===
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STATE_EVALUATED,
                trace_id, session_id, dag_state,
                {
                    "plan_id": dag_state.plan.plan_id,
                    "state_id": current_state.state_id,
                    "state_satisfied": eval_result.state_satisfied,
                    "evaluation_reason": eval_result.evaluation_reason,
                    "gap_analysis": eval_result.gap_analysis,
                    "suggestion": eval_result.suggestion,
                    "criteria_checklist": eval_result.criteria_checklist,
                },
                self.event_publisher,
            )

            if eval_result.state_satisfied:
                # 评估通过：标记成功，cursor 推进
                state_runtime.status = DagNodeStatus.SUCCEEDED
                dag_state.state_runtimes[current_state.state_id] = (
                    state_runtime.model_dump()
                )
                # 将 State 结果合并到全局上下文
                dag_state.global_merged_context[current_state.state_id] = (
                    state_runtime.merged_output
                )
                dag_state.cursor += 1
            else:
                # 评估不通过
                if dag_state.plan_replan_count < 1:
                    # 首次不通过：压缩结果 + 重构 Plan
                    compressed_result = await self.state_compressor.compress(
                        trace_id=trace_id,
                        session_id=session_id,
                        state_runtime=state_runtime.model_dump(),
                        evaluation_result=eval_result.model_dump(),
                    )

                    # 构建重构上下文
                    replan_context = _build_replan_context(
                        dag_state=dag_state,
                        current_state=current_state,
                        state_runtime=state_runtime,
                        eval_result=eval_result,
                        compressed_result=compressed_result,
                    )

                    # 执行 Plan 重构
                    dag_state = await self.plan_replan.execute(
                        trace_id=trace_id,
                        session_id=session_id,
                        dag_state=dag_state,
                        replan_context=replan_context,
                    )

                    # === 发布 DAG Plan 重构事件 ===
                    await _emit_dag_event(
                        DagWorkflowEventType.EVT_DAG_PLAN_REPLANNED,
                        trace_id, session_id, dag_state,
                        {
                            "plan_id": dag_state.plan.plan_id,
                            "replan_reason": eval_result.evaluation_reason,
                            "modified_states": [
                                {
                                    "state_id": s.state_id,
                                    "order_index": s.order_index,
                                    "intent": s.intent,
                                    "goal": s.goal,
                                    "completion_criteria": [c.model_dump() for c in s.completion_criteria],
                                    "depends_on": s.depends_on,
                                }
                                for s in dag_state.plan.states
                            ],
                        },
                        self.event_publisher,
                    )

                    # 重构后 cursor 不变，重新执行当前 State
                    state_runtime.status = DagNodeStatus.DEGRADED
                    dag_state.state_runtimes[current_state.state_id] = (
                        state_runtime.model_dump()
                    )
                else:
                    # 已重试过：终止流程
                    state_runtime.status = DagNodeStatus.FAILED
                    dag_state.state_runtimes[current_state.state_id] = (
                        state_runtime.model_dump()
                    )
                    dag_state.terminated = True
                    dag_state.termination_reason = (
                        f"State 评估不通过且已达重构上限: "
                        f"{eval_result.evaluation_reason}"
                    )
                    dag_state.termination_state_id = current_state.state_id

            # 发布 State 执行完成状态
            await self.chat_status_publisher.publish(
                trace_id=trace_id,
                session_id=session_id,
                message_id="",
                stage=ChatStatusStage.DAG_STATE_EXECUTION,
                state=(
                    ChatStatusState.COMPLETED
                    if state_runtime.status == DagNodeStatus.SUCCEEDED
                    else ChatStatusState.ERROR
                ),
                display_text=get_chat_status_text(
                    ChatStatusStage.DAG_STATE_EXECUTION,
                    ChatStatusState.COMPLETED
                    if state_runtime.status == DagNodeStatus.SUCCEEDED
                    else ChatStatusState.ERROR,
                ),
                is_visible=True,
                is_terminal=True,
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] State 执行异常: "
                f"state_id={current_state.state_id}, error={exc}"
            )
            state_runtime.status = DagNodeStatus.FAILED
            state_runtime.error_messages.append(str(exc))
            dag_state.state_runtimes[current_state.state_id] = (
                state_runtime.model_dump()
            )
            dag_state.terminated = True
            dag_state.termination_reason = f"State 执行异常: {exc}"
            dag_state.termination_state_id = current_state.state_id

        # 持久化预算消耗到 DagEngineState
        dag_state.budget_consumed["tool_calls"] = budget_tracker.global_consumed

        # 写回 ChatWorkflowState
        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")

        return Command(
            update={"dag_state": chat_state.dag_state.model_dump(mode="json")},
            goto=DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
        )


# ===========================================================================
# 节点 3: DagCursorRouterNode — Cursor 路由节点
# ===========================================================================


class DagCursorRouterNode:
    """Cursor 路由节点 — LangGraph 子图节点。

    做什么：作为 LangGraph 子图的路由决策源节点。
    为什么这样做：LangGraph 条件边需要一个源节点作为路由起点，
                  DagCursorRouterNode 作为该源节点存在（自身不做任何状态更新），
                  实际路由决策由 add_conditional_edges 的路由函数完成。
    注意：此节点是 checkpoint 持久化点，LangGraph 在此节点完成后保存状态快照，
          确保断点恢复时能从此处继续。
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口（无操作，仅作为条件边源节点和 checkpoint 点）。

        返回:
            dict: 空字典，不修改任何状态。
        """
        return {}


# ===========================================================================
# 节点 4: DagPlanSummarizerNode — Plan 结果汇总节点
# ===========================================================================


class DagPlanSummarizerNode:
    """Plan 结果汇总节点 — LangGraph 子图节点。

    做什么：执行 Plan 结果汇总，发布完成/终止事件，
           将汇总结果写回 ChatWorkflowState。
    为什么这样做：对应原 DagEngine.run() 中的 Phase 3 逻辑和 _apply_dag_result 逻辑。
                  汇总完成后，子图结束，控制权返回外层图。
    """

    def __init__(
        self,
        plan_summary: PlanResultSummaryNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化 Plan 结果汇总节点。

        参数:
            plan_summary: Plan 结果汇总子节点实例。
            chat_status_publisher: Chat 状态发布器。
            event_publisher: DAG 工作流事件发布器。
        """
        self.plan_summary = plan_summary
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行 Plan 结果汇总。

        做什么：
        1. 从 ChatWorkflowState 读取 DagEngineState
        2. 调用 plan_summary.execute() 生成汇总
        3. 写入 dag_state.plan_summary
        4. 发布 EVT_DAG_PLAN_COMPLETED 或 EVT_DAG_PLAN_TERMINATED
        5. 将汇总结果写回 ChatWorkflowState（is_dag_active、plan_summary_text 等）
        6. 发布引擎完成状态

        返回:
            dict: 更新后的 ChatWorkflowState 图状态。
        """
        chat_state = ChatWorkflowState.from_graph_state(state)
        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 反序列化 DagEngineState
        dag_engine_data = chat_state.dag_state.dag_engine_state
        if not dag_engine_data:
            logger.warning(
                f"[TraceID:{trace_id}] Summarizer: dag_engine_state 为空"
            )
            chat_state.dag_state.is_dag_active = True
            return chat_state.as_graph_state()

        dag_state = DagEngineState(**dag_engine_data)
        started_at_ms = dag_state.workflow_state.get("dag_engine_started_at_ms", 0)

        summary_result = None
        try:
            # ============================================================
            # Phase 3: Plan 结果汇总
            # ============================================================
            summary_result = await self.plan_summary.execute(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
            )

            dag_state.plan_summary = summary_result.model_dump()

            elapsed_ms = int(time.time() * 1000) - started_at_ms if started_at_ms else 0
            logger.info(
                f"[TraceID:{trace_id}] DAG 引擎执行完成: "
                f"states={len(dag_state.plan.states)}, "
                f"cursor={dag_state.cursor}, "
                f"terminated={dag_state.terminated}, "
                f"elapsed_ms={elapsed_ms}"
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] Plan 结果汇总异常: {exc}"
            )
            dag_state.terminated = True
            dag_state.termination_reason = (
                f"{dag_state.termination_reason or ''} 汇总异常: {exc}"
            ).strip()

        # 发布引擎入口完成状态
        await self.chat_status_publisher.publish(
            trace_id=trace_id,
            session_id=session_id,
            message_id="",
            stage=ChatStatusStage.DAG_ENGINE_ENTRY,
            state=ChatStatusState.COMPLETED,
            display_text=get_chat_status_text(
                ChatStatusStage.DAG_ENGINE_ENTRY, ChatStatusState.COMPLETED
            ),
            is_visible=True,
            is_terminal=True,
        )

        # === 发布 DAG Plan 完成/终止事件 ===
        if dag_state.terminated:
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_PLAN_TERMINATED,
                trace_id, session_id, dag_state,
                {
                    "plan_id": dag_state.plan.plan_id,
                    "termination_reason": dag_state.termination_reason,
                    "termination_state_id": dag_state.termination_state_id,
                    "partial_results": summary_result.overall_result if summary_result else "",
                },
                self.event_publisher,
            )
        else:
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_PLAN_COMPLETED,
                trace_id, session_id, dag_state,
                {
                    "plan_id": dag_state.plan.plan_id,
                    "total_states": summary_result.total_states if summary_result else len(dag_state.plan.states),
                    "succeeded_states": summary_result.succeeded_states if summary_result else 0,
                    "degraded_states": summary_result.degraded_states if summary_result else 0,
                    "failed_states": summary_result.failed_states if summary_result else 0,
                    "overall_result": summary_result.overall_result if summary_result else "",
                    "execution_highlights": summary_result.execution_highlights if summary_result else [],
                    "execution_issues": summary_result.execution_issues if summary_result else [],
                },
                self.event_publisher,
            )

        # === 将 DAG 结果写回 ChatWorkflowState（原 _apply_dag_result 逻辑） ===
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

        return chat_state.as_graph_state()


# ===========================================================================
# 子图工厂函数
# ===========================================================================


def build_plan_cursor_subgraph(
    plan_generation: PlanGenerationNode,
    skill_screening: SkillScreeningNode,
    step_plan: StepPlanNode,
    step_executor: StepExecutor,
    step_retry: StepRetryPolicy,
    step_merge: StepMergeNode,
    state_evaluation: StateEvaluationNode,
    state_compressor: StateResultCompressor,
    plan_replan: PlanReplanNode,
    plan_summary: PlanResultSummaryNode,
    chat_status_publisher: ChatStatusPublisher,
    event_publisher: ChatWorkflowEventPublisher | None = None,
    memory_manager: Any = None,
    rag_orchestrator: Any = None,
    mcp_tool_registry: Any = None,
):
    """构建 Plan + Cursor 子图。

    做什么：创建 4 节点 LangGraph 图：Planner → Executor → Router → Summary。
    为什么这样做：将原 DagEngine.run() 中的 Python while 循环拆分为
                  由 LangGraph 图结构驱动的迭代，每个 State 执行都是
                  独立的图节点调用，天然享受 Checkpoint 断点恢复能力。
    参数:
        plan_generation: Plan 生成子节点。
        skill_screening: Skill 初筛子节点。
        step_plan: Step Plan 生成子节点。
        step_executor: Step 执行子节点。
        step_retry: Step 重试策略。
        step_merge: Step 合并子节点。
        state_evaluation: State 评估子节点。
        state_compressor: State 结果压缩器。
        plan_replan: Plan 重构子节点。
        plan_summary: Plan 结果汇总子节点。
        chat_status_publisher: Chat 状态发布器。
        event_publisher: DAG 工作流事件发布器。
        memory_manager: 记忆管理器。
        rag_orchestrator: RAG 检索编排器。
        mcp_tool_registry: MCP 工具注册中心。
    返回:
        CompiledGraph: 编译后的子图，可被 DagEngineNode 作为 ainvoke 调用。
    """
    graph = StateGraph(ChatWorkflowState)

    # --- 创建 4 个节点实例 ---
    planner = DagPlannerNode(
        plan_generation=plan_generation,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )
    executor = DagStateExecutorNode(
        skill_screening=skill_screening,
        step_plan=step_plan,
        step_executor=step_executor,
        step_retry=step_retry,
        step_merge=step_merge,
        state_evaluation=state_evaluation,
        state_compressor=state_compressor,
        plan_replan=plan_replan,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
        memory_manager=memory_manager,
        rag_orchestrator=rag_orchestrator,
        mcp_tool_registry=mcp_tool_registry,
    )
    router = DagCursorRouterNode()
    summarizer = DagPlanSummarizerNode(
        plan_summary=plan_summary,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )

    # --- 注册 4 个节点 ---
    graph.add_node(DagSubGraphNodeName.DAG_PLANNER.value, planner)
    graph.add_node(DagSubGraphNodeName.DAG_STATE_EXECUTOR.value, executor)
    graph.add_node(DagSubGraphNodeName.DAG_CURSOR_ROUTER.value, router)
    graph.add_node(DagSubGraphNodeName.DAG_PLAN_SUMMARIZER.value, summarizer)

    # --- 入口 → Planner ---
    graph.set_entry_point(DagSubGraphNodeName.DAG_PLANNER.value)

    # --- Planner → Executor ---
    graph.add_edge(
        DagSubGraphNodeName.DAG_PLANNER.value,
        DagSubGraphNodeName.DAG_STATE_EXECUTOR.value,
    )

    # --- Executor → Router ---
    # Command(goto) 会跳过此边直接跳到 Router，但 add_edge 仍需注册以满足拓扑校验
    graph.add_edge(
        DagSubGraphNodeName.DAG_STATE_EXECUTOR.value,
        DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
    )

    # --- Router → Executor（循环）或 Summary（退出） ---
    graph.add_conditional_edges(
        DagSubGraphNodeName.DAG_CURSOR_ROUTER.value,
        route_by_cursor_from_graph_state,
        {
            DagCursorRoute.CONTINUE.value: DagSubGraphNodeName.DAG_STATE_EXECUTOR.value,
            DagCursorRoute.COMPLETE.value: DagSubGraphNodeName.DAG_PLAN_SUMMARIZER.value,
            DagCursorRoute.TERMINATE.value: DagSubGraphNodeName.DAG_PLAN_SUMMARIZER.value,
        },
    )

    # --- Summary → END ---
    graph.add_edge(
        DagSubGraphNodeName.DAG_PLAN_SUMMARIZER.value,
        END,
    )

    return graph.compile()
