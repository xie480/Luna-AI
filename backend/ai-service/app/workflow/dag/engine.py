"""Phase 9 DAG 引擎 — Plan + Cursor 子图工厂。

做什么：将原 DagEngine 单体引擎重构为 Plan + Cursor 子图工厂，
        包含 4 个独立 LangGraph 节点：Planner / Executor / Router / Summary。
        其中 Executor 节点进一步拆解为 4 节点子图：
        SkillScreening → StepPlan → StepExecutor(循环) → StateEvaluator。
为什么这样做：原 DagEngine.run() 内部使用 Python while 循环驱动 State 执行，
              整个 Plan 执行是一次不可分割的 LangGraph 节点调用，无法享受
              Checkpoint 断点恢复能力。重构后每个 State 执行和每个 Step 执行
              都是独立的 LangGraph 节点调用，天然享受 Checkpoint 断点恢复能力。

核心公式：
  动态 DAG = 固定 Graph（4 个节点）+ Plan（任务列表）+ Cursor（执行指针）
  其中 Executor = 固定子图（4 个节点）+ Step 列表 + StepCursor（执行指针）
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
from app.workflow.constants import (
    DagEvalRoute,
    DagExecutorSubGraphNodeName,
    DagStepCursorRoute,
    DagSubGraphNodeName,
    DagWorkflowEventType,
)
from app.workflow.dag.types import DagCursorRoute
from app.workflow.context import ChatWorkflowState
from app.workflow.dag.budget import BudgetTracker
from app.workflow.dag.evaluation import StateResultCompressor
from app.workflow.dag.nodes.cursor_router import (
    route_by_cursor_from_graph_state,
    route_by_eval,
    route_by_step_cursor,
)
from app.workflow.dag.nodes.plan_generation import PlanGenerationNode
from app.workflow.dag.nodes.plan_replan import PlanReplanNode
from app.workflow.dag.nodes.plan_summary import PlanResultSummaryNode
from app.workflow.dag.nodes.skill_screening import SkillScreeningNode
from app.workflow.dag.nodes.state_evaluation import StateEvaluationNode
from app.workflow.dag.nodes.step_executor import StepExecutor, StepRetryPolicy
from app.workflow.dag.nodes.step_merge import StepMergeNode
from app.workflow.dag.nodes.step_plan import StepPlanNode
from app.workflow.dag.types import (
    DagEngineState,
    DagExecutorRuntimeState,
    DagNodeStatus,
    DagNodeType,
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
        from app.api.sse import sse_manager
        await sse_manager.publish({
            "type": event_type.value,
            "trace_id": trace_id,
            "payload": payload,
        })
    except Exception as exc:
        logger.warning(f"DAG 事件发布失败: type={event_type.value}, error={exc}")


def _build_state_context_from_runtime(
    dag_state: DagEngineState,
    executor_rt: DagExecutorRuntimeState,
    session_id: str,
    memory_manager: Any,
    rag_orchestrator: Any,
    mcp_tool_registry: Any,
) -> dict[str, Any]:
    """从 DagExecutorRuntimeState 构建 state_context。

    做什么：将 DAG 引擎的状态注入到 state_context 中，供各原子节点执行时读取。
    为什么这样做：原子节点（StepExecutor 等）需要访问 session_id、
                  memory_manager 等运行时依赖，通过 state_context 字典传递。
    """
    return {
        "session_id": session_id,
        "user_id": dag_state.workflow_state.get("runtime", {}).get(
            "user_id", "local_default_user"
        ),
        "trace_id": dag_state.plan.trace_id,
        "state_goal": executor_rt.current_state_goal,
        "state_intent": executor_rt.current_state_intent,
        "skill_registry": mcp_tool_registry,
        "memory_manager": memory_manager,
        "rag_orchestrator": rag_orchestrator,
        "disambiguated_text": dag_state.disambiguated_text,
        "session_context": dag_state.session_context,
        "user_profile": dag_state.user_profile,
        "memory_context": dag_state.memory_context,
        "partitioned_outputs": executor_rt.all_partitioned_outputs,
        "current_step_context": {},
        "steps_total": len(executor_rt.steps),
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
    """
    completed_states = []
    for sid, runtime_data in dag_state.state_runtimes.items():
        if runtime_data.get("status") == DagNodeStatus.SUCCEEDED.value:
            completed_states.append({
                "state_id": sid,
                "responsibility": runtime_data.get("responsibility", ""),
                "intent": runtime_data.get("intent", ""),
                "goal": runtime_data.get("goal", ""),
            })

    remaining_states = []
    for state_def in dag_state.plan.states[dag_state.cursor + 1:]:
        remaining_states.append({
            "state_id": state_def.state_id,
            "order_index": state_def.order_index,
            "responsibility": state_def.responsibility,
            "intent": state_def.intent,
            "goal": state_def.goal,
        })

    return ReplanContext(
        failed_state_id=current_state.state_id,
        failed_state_responsibility=current_state.responsibility,
        failed_state_intent=current_state.intent,
        failed_state_goal=current_state.goal,
        failed_state_result=compressed_result,
        evaluation_reason=eval_result.evaluation_reason,
        gap_analysis=eval_result.gap_analysis,
        suggestion=eval_result.suggestion,
        completed_states=completed_states,
        remaining_states=remaining_states,
        global_objective=dag_state.global_objective,
    )


def _serialize_node_def_map(steps: list[Any]) -> dict[str, Any]:
    """将 StepDefinition 列表中的 node_id → node_def 映射序列化。

    做什么：遍历所有 Step 的节点定义，构建 node_id → 序列化字典的映射。
    为什么这样做：NODE_STARTED/COMPLETED 事件需要通过 node_id 查找节点类型。
    """
    node_def_map: dict[str, Any] = {}
    for step in steps:
        for n in step.nodes:
            node_def_map[n.node_id] = {
                "node_id": n.node_id,
                "node_type": n.node_type.value if hasattr(n.node_type, 'value') else str(n.node_type),
                "skill_name": n.skill_name,
                "tool_name": n.tool_name,
            }
    return node_def_map


def _extract_dag_state_from_graph(state: dict[str, Any]) -> tuple[ChatWorkflowState, DagEngineState | None]:
    """从图状态中提取 ChatWorkflowState 和 DagEngineState。

    做什么：反序列化 ChatWorkflowState，再从 dag_engine_state 中提取 DagEngineState。
    返回: (chat_state, dag_state_or_none)
    """
    chat_state = ChatWorkflowState.from_graph_state(state)
    dag_engine_data = chat_state.dag_state.dag_engine_state
    if not dag_engine_data:
        return chat_state, None
    dag_state = DagEngineState(**dag_engine_data)
    return chat_state, dag_state


def _save_dag_state_to_graph(
    chat_state: ChatWorkflowState,
    dag_state: DagEngineState,
) -> dict[str, Any]:
    """将 DagEngineState 写回 ChatWorkflowState 并返回图状态。

    做什么：序列化 DagEngineState 到 dag_engine_state 字段，
           然后序列化 ChatWorkflowState 为图状态字典。
    """
    chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
    return chat_state.as_graph_state()


def _reset_executor_runtime(dag_state: DagEngineState, current_state: Any) -> None:
    """重置 Executor 子图运行时状态（每轮 skill 筛选开始时调用）。

    做什么：清空 executor_runtime 中的临时数据，保留 budget 和已完成的信息。
    为什么这样做：评估不通过重走 skill 筛选时，需要重置子图内的临时状态。
    """
    dag_state.executor_runtime = DagExecutorRuntimeState(
        current_state_id=current_state.state_id,
        current_state_goal=current_state.goal,
        current_state_intent=current_state.intent,
        current_state_order_index=current_state.order_index,
        completion_criteria=[c.model_dump() for c in current_state.completion_criteria],
        state_runtime=StateRuntimeState(
            state_id=current_state.state_id,
            status=DagNodeStatus.RUNNING,
            responsibility=current_state.responsibility,
            intent=current_state.intent,
            goal=current_state.goal,
        ).model_dump(),
        budget_global_consumed=dag_state.budget_consumed.get("tool_calls", 0),
        initialized=True,
    ).model_dump()


# ===========================================================================
# Executor 子图节点 1: ExecutorSkillScreeningNode — Skill 初筛
# ===========================================================================


class ExecutorSkillScreeningNode:
    """Executor 子图 — Skill 初筛节点。

    做什么：从 DagEngineState 中读取当前 State 信息，
           调用 SkillScreeningNode 执行 Skill 初筛，
           将结果写入 executor_runtime。
    为什么这样做：对应原 DagStateExecutorNode 中的 Skill 初筛逻辑段。
    """

    def __init__(
        self,
        skill_screening: SkillScreeningNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.skill_screening = skill_screening
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 子图节点入口 — 执行 Skill 初筛。

        做什么：
        1. 从图状态提取 DagEngineState 和 ExecutorRuntimeState
        2. 如果未初始化（首次进入），执行完整初始化
        3. 如果是 eval_retry 回退，重置 executor_runtime
        4. 调用 skill_screening.execute()
        5. 发布 EVT_DAG_SKILL_SCREENING 事件
        6. 返回更新后的图状态
        """
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        executor_rt = DagExecutorRuntimeState(**dag_state.executor_runtime)

        # 如果 state_runtime 状态为 DEGRADED（eval_retry 回退），重置 executor_runtime
        state_rt = executor_rt.state_runtime
        if state_rt.get("status") == DagNodeStatus.DEGRADED.value:
            current_state = dag_state.plan.states[dag_state.cursor]
            _reset_executor_runtime(dag_state, current_state)
            executor_rt = DagExecutorRuntimeState(**dag_state.executor_runtime)

        # 如果 selected_skills 已有数据（非首次），跳过重复筛选
        if executor_rt.selected_skills:
            logger.info(
                f"[TraceID:{trace_id}] SkillScreeningSubNode: "
                f"已有筛选结果，跳过重复筛选"
            )
            return _save_dag_state_to_graph(chat_state, dag_state)

        current_state = dag_state.plan.states[dag_state.cursor]

        try:
            # 检测 Plan 阶段预分配的 Skill 筛选结果
            # 做什么：如果 Plan 生成时已为该 State 同步输出了 selected_skills，
            #         则直接使用预分配结果，跳过 LLM 调用，减少 token 消耗。
            # 为什么这样做：Plan 生成 Prompt 已要求 LLM 同步输出每个 State 的
            #               Skill 筛选结果，避免每个 State 再单独调用一次 SkillScreening。
            if current_state.pre_allocated_skills:
                logger.info(
                    f"[TraceID:{trace_id}] SkillScreeningSubNode: "
                    f"检测到 Plan 阶段预分配的 Skill，"
                    f"count={len(current_state.pre_allocated_skills)}，"
                    f"跳过 LLM 调用"
                )
                selected_skills = current_state.pre_allocated_skills
            else:
                selected_skills = await self.skill_screening.execute(
                    trace_id=trace_id,
                    session_id=session_id,
                    dag_state=dag_state,
                    state_goal=current_state.goal,
                    state_intent=current_state.intent,
                    completion_criteria=[
                        c.model_dump() for c in current_state.completion_criteria
                    ],
                    state_responsibility=current_state.responsibility,
                )
            executor_rt.selected_skills = selected_skills

            # === 发布 DAG Skill 初筛事件 ===
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_SKILL_SCREENING,
                trace_id, session_id, dag_state,
                {
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
                },
                self.event_publisher,
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] SkillScreeningSubNode 异常: {exc}"
            )
            executor_rt.state_runtime["status"] = DagNodeStatus.FAILED.value
            dag_state.terminated = True
            dag_state.termination_reason = f"Skill 初筛异常: {exc}"
            dag_state.termination_state_id = current_state.state_id

        dag_state.executor_runtime = executor_rt.model_dump()
        return _save_dag_state_to_graph(chat_state, dag_state)


# ===========================================================================
# Executor 子图节点 2: ExecutorStepPlanNode — Step Plan 生成
# ===========================================================================


class ExecutorStepPlanNode:
    """Executor 子图 — Step Plan 生成节点。

    做什么：从 executor_runtime 读取筛选后的 Skill 列表，
           调用 StepPlanNode 生成 Step 执行计划，
           将结果写入 executor_runtime.steps。
    为什么这样做：对应原 DagStateExecutorNode 中的 Step Plan 生成逻辑段。
    """

    def __init__(
        self,
        step_plan: StepPlanNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.step_plan = step_plan
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 子图节点入口 — 生成 Step 执行计划。"""
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        executor_rt = DagExecutorRuntimeState(**dag_state.executor_runtime)

        # 如果已有 steps（eval_retry 回退时 skill 筛选可能产生新 plan），跳过
        # 实际上 eval_retry 会重置 executor_runtime，所以 steps 为空
        if executor_rt.steps:
            logger.info(
                f"[TraceID:{trace_id}] StepPlanSubNode: "
                f"已有 Step Plan，跳过重复生成"
            )
            return _save_dag_state_to_graph(chat_state, dag_state)

        # 如果已终止，跳过
        if dag_state.terminated:
            return _save_dag_state_to_graph(chat_state, dag_state)

        current_state = dag_state.plan.states[dag_state.cursor]

        # 构建 state_context
        state_context = _build_state_context_from_runtime(
            dag_state=dag_state,
            executor_rt=executor_rt,
            session_id=session_id,
            memory_manager=None,
            rag_orchestrator=None,
            mcp_tool_registry=None,
        )
        # 从原始 workflow_state 恢复运行时依赖
        if dag_state.workflow_state:
            # memory_manager/rag_orchestrator/mcp_tool_registry 不可序列化，
            # 在 state_context 中已设为 None，实际使用时通过 skill_registry 注入
            pass

        try:
            steps = await self.step_plan.execute(
                trace_id=trace_id,
                session_id=session_id,
                state_goal=current_state.goal,
                state_intent=current_state.intent,
                selected_skills=executor_rt.selected_skills,
                state_context=state_context,
                state_responsibility=current_state.responsibility,
            )

            executor_rt.steps = [s.model_dump() for s in steps]
            executor_rt.state_runtime["steps_total"] = len(steps)
            executor_rt.state_runtime["step_plan"] = executor_rt.steps
            executor_rt.node_def_map = _serialize_node_def_map(steps)
            executor_rt.step_cursor = 0

            # === 发布 DAG Step Plan 生成事件 ===
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_STEP_PLAN_GENERATED,
                trace_id, session_id, dag_state,
                {
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
                },
                self.event_publisher,
            )

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] StepPlanSubNode 异常: {exc}"
            )
            executor_rt.state_runtime["status"] = DagNodeStatus.FAILED.value
            executor_rt.state_runtime["error_messages"] = [str(exc)]
            dag_state.terminated = True
            dag_state.termination_reason = f"Step Plan 生成失败: {exc}"
            dag_state.termination_state_id = current_state.state_id

        dag_state.executor_runtime = executor_rt.model_dump()
        return _save_dag_state_to_graph(chat_state, dag_state)


# ===========================================================================
# Executor 子图节点 3: ExecutorStepExecNode — 单个 Step 执行
# ===========================================================================


class ExecutorStepExecNode:
    """Executor 子图 — 单个 Step 执行节点。

    做什么：从 executor_runtime 读取 steps[step_cursor]，
           执行当前 Step（带重试），推进 step_cursor，
           发布 NODE_STARTED/COMPLETED 事件。
           Phase 13 增强：当工具节点触发 L2/L3 Gating 审批时，
           检测 gating_pending 标志，标记子图为 gating_suspended 并
           优雅退出子图，等待用户审批结果后再恢复执行。
    为什么这样做：对应原 DagStateExecutorNode 中的逐 Step 执行循环体。
                  每次调用只执行一个 Step，由 LangGraph 条件路由驱动循环。
    """

    def __init__(
        self,
        step_retry: StepRetryPolicy,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
        memory_manager: Any = None,
        rag_orchestrator: Any = None,
        mcp_tool_registry: Any = None,
        gating_service: Any = None,
        snapshot_manager: Any = None,
    ):
        self.step_retry = step_retry
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher
        self._memory_manager = memory_manager
        self._rag_orchestrator = rag_orchestrator
        self._mcp_tool_registry = mcp_tool_registry
        self._gating_service = gating_service
        self._snapshot_manager = snapshot_manager

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 子图节点入口 — 执行当前 Step。

        做什么：
        1. 读取 steps[step_cursor]
        2. 检查预算
        3. 发射 NODE_STARTED 事件
        4. 带重试执行 Step
        5. 统计成功/失败，发射 NODE_COMPLETED 事件
        6. 推进 step_cursor
        """
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        executor_rt = DagExecutorRuntimeState(**dag_state.executor_runtime)

        # 如果已终止，跳过
        if dag_state.terminated:
            return _save_dag_state_to_graph(chat_state, dag_state)

        step_idx = executor_rt.step_cursor
        steps_data = executor_rt.steps

        # 边界守卫
        if step_idx >= len(steps_data):
            return _save_dag_state_to_graph(chat_state, dag_state)

        current_step_data = steps_data[step_idx]

        # 从序列化数据重建 StepDefinition 用于执行
        from app.workflow.dag.types import StepDefinition
        step_def = StepDefinition(**current_step_data)

        # 恢复 BudgetTracker
        budget_tracker = BudgetTracker(
            state_budget=StateBudget(),
            global_budget=dag_state.plan.global_budget,
            trace_id=trace_id,
        )
        budget_tracker.global_consumed = executor_rt.budget_global_consumed

        # 检查预算
        if budget_tracker.is_state_budget_exhausted():
            logger.warning(
                f"[TraceID:{trace_id}] StepExecSubNode: State 预算耗尽，跳过"
            )
            executor_rt.state_runtime["budget_exhausted"] = True
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
            dag_state.executor_runtime = executor_rt.model_dump()
            return _save_dag_state_to_graph(chat_state, dag_state)

        if budget_tracker.is_global_budget_exhausted():
            logger.warning(
                f"[TraceID:{trace_id}] StepExecSubNode: Plan 全局预算耗尽"
            )
            dag_state.terminated = True
            dag_state.termination_reason = "Plan 全局预算耗尽"
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
            dag_state.executor_runtime = executor_rt.model_dump()
            return _save_dag_state_to_graph(chat_state, dag_state)

        current_state_id = executor_rt.current_state_id
        node_def_map = executor_rt.node_def_map

        # === 发射 Step 内所有节点的 NODE_STARTED 事件 ===
        for node_in_step in step_def.nodes:
            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_NODE_STARTED,
                trace_id, session_id, dag_state,
                {
                    "plan_id": dag_state.plan.plan_id,
                    "state_id": current_state_id,
                    "step_id": step_def.step_id,
                    "node_id": node_in_step.node_id,
                    "node_type": node_in_step.node_type.value
                        if hasattr(node_in_step.node_type, 'value')
                        else str(node_in_step.node_type),
                },
                self.event_publisher,
            )

        # 构建 state_context
        state_context = _build_state_context_from_runtime(
            dag_state=dag_state,
            executor_rt=executor_rt,
            session_id=session_id,
            memory_manager=self._memory_manager,
            rag_orchestrator=self._rag_orchestrator,
            mcp_tool_registry=self._mcp_tool_registry,
        )
        state_context["steps_total"] = len(steps_data)

        # Phase 13：将 gating 依赖注入到 state_context，供 ToolExecuteNode 使用
        # 做什么：优先使用构造函数注入的实例（如果可用）；
        #         否则从 FastAPI app.state 读取（因为 GatingService 在
        #         ChatWorkflowService 之后才初始化，构造时可能为 None）。
        # 为什么这样做：与 mcp_skill_execution_node.py 保持一致的读取策略。
        gating_svc = self._gating_service
        snap_mgr = self._snapshot_manager
        if not gating_svc:
            try:
                from app.main import app as _fastapi_app
                gating_svc = getattr(_fastapi_app.state, "gating_service", None)
                if not snap_mgr:
                    redis_client = getattr(_fastapi_app.state, "redis_client", None)
                    if redis_client:
                        from app.gating.snapshot import GatingSnapshotManager
                        snap_mgr = GatingSnapshotManager(redis_client)
            except Exception:
                pass
        state_context["gating_service"] = gating_svc
        state_context["snapshot_manager"] = snap_mgr

        # 带重试执行 Step
        step_outputs, step_errors = await self.step_retry.execute_with_retry(
            trace_id=trace_id,
            step_def=step_def,
            state_context=state_context,
        )

        # Phase 13：检测 Gating 审批挂起
        # 做什么：如果任意工具节点返回 gating_pending=True，说明 L2/L3 工具
        #         已创建审批请求，正在等待用户确认。
        #         此时不应视为执行失败，而是标记 gating_suspended 并优雅退出子图。
        # 为什么这样做：审批挂起是正常的业务流程，不是错误。
        #              子图退出后，外层 DAG 图会在下一轮执行时通过
        #              session_context_load_node 消费审批结果。
        gating_suspended = False
        if step_outputs:
            gating_pending_nodes = [
                nid for nid, out in step_outputs.items()
                if out.get("gating_pending", False)
            ]
            if gating_pending_nodes:
                gating_suspended = True
                logger.info(
                    f"[TraceID:{trace_id}] StepExecSubNode: "
                    f"工具 Gating 审批挂起，nodes={gating_pending_nodes}，"
                    f"标记 gating_suspended 并退出子图"
                )
                # 将 gating 信息写入 dag_state，供外层图使用
                dag_state.gating_suspended = True
                dag_state.gating_pending_node_ids = gating_pending_nodes

        if step_outputs:
            executor_rt.all_partitioned_outputs.update(step_outputs)
        if step_errors:
            errors = executor_rt.state_runtime.get("error_messages", [])
            errors.extend(step_errors)
            executor_rt.state_runtime["error_messages"] = errors

        executor_rt.state_runtime["steps_completed"] = (
            executor_rt.state_runtime.get("steps_completed", 0) + 1
        )

        # 如果处于 Gating 挂起状态，提前退出，不推进 step_cursor
        if gating_suspended:
            dag_state.executor_runtime = executor_rt.model_dump()
            return _save_dag_state_to_graph(chat_state, dag_state)

        # 统计成功/失败节点并发射 NODE_COMPLETED 事件
        for nid, out in step_outputs.items():
            success = out.get("success", True)
            if success:
                executor_rt.state_runtime["nodes_succeeded"] = (
                    executor_rt.state_runtime.get("nodes_succeeded", 0) + 1
                )
            else:
                executor_rt.state_runtime["nodes_failed"] = (
                    executor_rt.state_runtime.get("nodes_failed", 0) + 1
                )

            # 每个工具执行节点消耗一次预算配额
            nd = node_def_map.get(nid, {})
            if nd.get("node_type") == DagNodeType.TOOL_EXECUTE.value:
                budget_tracker.consume_tool_call()

            await _emit_dag_event(
                DagWorkflowEventType.EVT_DAG_NODE_COMPLETED,
                trace_id, session_id, dag_state,
                {
                    "plan_id": dag_state.plan.plan_id,
                    "state_id": current_state_id,
                    "step_id": step_def.step_id,
                    "node_id": nid,
                    "node_type": nd.get("node_type", "unknown"),
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

        # 推进 step_cursor
        executor_rt.step_cursor = step_idx + 1

        # 持久化预算消耗
        executor_rt.budget_global_consumed = budget_tracker.global_consumed
        dag_state.budget_consumed["tool_calls"] = budget_tracker.global_consumed

        dag_state.executor_runtime = executor_rt.model_dump()
        return _save_dag_state_to_graph(chat_state, dag_state)


# ===========================================================================
# Executor 子图节点 4: ExecutorStateEvalNode — State 评估
# ===========================================================================


class ExecutorStateEvalNode:
    """Executor 子图 — State 评估节点。

    做什么：所有 Step 执行完毕后，执行 Step 合并和 State 评估，
           根据评估结果决定：通过→标记成功 / 不通过→压缩+重构 或 终止。
    为什么这样做：对应原 DagStateExecutorNode 中的评估 + 重构逻辑段。
    """

    def __init__(
        self,
        step_merge: StepMergeNode,
        state_evaluation: StateEvaluationNode,
        state_compressor: StateResultCompressor,
        plan_replan: PlanReplanNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.step_merge = step_merge
        self.state_evaluation = state_evaluation
        self.state_compressor = state_compressor
        self.plan_replan = plan_replan
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 子图节点入口 — 执行 State 评估。"""
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        executor_rt = DagExecutorRuntimeState(**dag_state.executor_runtime)

        # 如果已终止，跳过评估
        if dag_state.terminated:
            return _save_dag_state_to_graph(chat_state, dag_state)

        current_state = dag_state.plan.states[dag_state.cursor]
        state_rt_data = executor_rt.state_runtime
        state_runtime = StateRuntimeState(**state_rt_data)

        try:
            # Step 合并
            state_runtime.partitioned_outputs = executor_rt.all_partitioned_outputs
            merge_result = await self.step_merge.merge(
                trace_id=trace_id,
                session_id=session_id,
                partitioned_outputs=executor_rt.all_partitioned_outputs,
            )
            state_runtime.merged_output = merge_result.get("merged_output", {})

            # State 评估
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
                state_responsibility=current_state.responsibility,
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
                    "check": eval_result.check or "",
                },
                self.event_publisher,
            )

            if eval_result.state_satisfied:
                # 评估通过：标记成功，cursor 推进
                state_runtime.status = DagNodeStatus.SUCCEEDED
                dag_state.state_runtimes[current_state.state_id] = (
                    state_runtime.model_dump()
                )
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

                    replan_context = _build_replan_context(
                        dag_state=dag_state,
                        current_state=current_state,
                        state_runtime=state_runtime,
                        eval_result=eval_result,
                        compressed_result=compressed_result,
                    )

                    dag_state = await self.plan_replan.execute(
                        trace_id=trace_id,
                        session_id=session_id,
                        dag_state=dag_state,
                        replan_context=replan_context,
                    )

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
                                    "responsibility": s.responsibility,
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

                    # 重构后标记 DEGRADED，子图回退到 skill_screening
                    state_runtime.status = DagNodeStatus.DEGRADED
                    dag_state.state_runtimes[current_state.state_id] = (
                        state_runtime.model_dump()
                    )
                    executor_rt.state_runtime = state_runtime.model_dump()
                    dag_state.executor_runtime = executor_rt.model_dump()
                    return _save_dag_state_to_graph(chat_state, dag_state)
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
                f"[TraceID:{trace_id}] StateEvalSubNode 异常: "
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

        executor_rt.state_runtime = state_runtime.model_dump()
        dag_state.executor_runtime = executor_rt.model_dump()
        return _save_dag_state_to_graph(chat_state, dag_state)


# ===========================================================================
# Executor 子图工厂
# ===========================================================================


def build_state_executor_subgraph(
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
    gating_service: Any = None,
    snapshot_manager: Any = None,
):
    """构建 State Executor 子图。

    做什么：创建 4 节点 LangGraph 子图：
           SkillScreening → StepPlan → StepExecutor(循环) → StateEvaluator。
    为什么这样做：将原 DagStateExecutorNode 中的单体逻辑拆分为
                  由 LangGraph 图结构驱动的迭代，每个 Step 执行都是
                  独立的图节点调用，天然享受 Checkpoint 断点恢复能力。
    子图路由逻辑：
        - step_executor 执行完后通过 step_cursor_router 判断
          → 有剩余 step 则循环执行下一个
          → 无剩余 step 则进入 state_evaluator
        - state_evaluator 评估不通过时回退到 skill_screening 重走
        - 评估通过或终止则子图结束

    返回:
        CompiledGraph: 编译后的子图，可被外层图作为 dag_state_executor 节点使用。
    """
    graph = StateGraph(ChatWorkflowState)

    # --- 创建 4 个子节点实例 ---
    screening_node = ExecutorSkillScreeningNode(
        skill_screening=skill_screening,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )
    step_plan_node = ExecutorStepPlanNode(
        step_plan=step_plan,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )
    step_exec_node = ExecutorStepExecNode(
        step_retry=step_retry,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
        memory_manager=memory_manager,
        rag_orchestrator=rag_orchestrator,
        mcp_tool_registry=mcp_tool_registry,
        gating_service=gating_service,
        snapshot_manager=snapshot_manager,
    )
    eval_node = ExecutorStateEvalNode(
        step_merge=step_merge,
        state_evaluation=state_evaluation,
        state_compressor=state_compressor,
        plan_replan=plan_replan,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )

    # --- 注册 4 个节点 ---
    graph.add_node(DagExecutorSubGraphNodeName.SKILL_SCREENING.value, screening_node)
    graph.add_node(DagExecutorSubGraphNodeName.STEP_PLAN.value, step_plan_node)
    graph.add_node(DagExecutorSubGraphNodeName.STEP_EXECUTOR.value, step_exec_node)
    graph.add_node(DagExecutorSubGraphNodeName.STATE_EVALUATOR.value, eval_node)

    # --- 入口 → SkillScreening ---
    graph.set_entry_point(DagExecutorSubGraphNodeName.SKILL_SCREENING.value)

    # --- SkillScreening → StepPlan ---
    graph.add_edge(
        DagExecutorSubGraphNodeName.SKILL_SCREENING.value,
        DagExecutorSubGraphNodeName.STEP_PLAN.value,
    )

    # --- StepPlan → StepExecutor ---
    graph.add_edge(
        DagExecutorSubGraphNodeName.STEP_PLAN.value,
        DagExecutorSubGraphNodeName.STEP_EXECUTOR.value,
    )

    # --- StepExecutor → StepCursorRouter（条件路由） ---
    # next_step → StepExecutor（循环执行下一个 Step）
    # all_done → StateEvaluator
    graph.add_conditional_edges(
        DagExecutorSubGraphNodeName.STEP_EXECUTOR.value,
        route_by_step_cursor,
        {
            DagStepCursorRoute.NEXT_STEP.value: DagExecutorSubGraphNodeName.STEP_EXECUTOR.value,
            DagStepCursorRoute.ALL_DONE.value: DagExecutorSubGraphNodeName.STATE_EVALUATOR.value,
        },
    )

    # --- StateEvaluator → EvalRouter（条件路由） ---
    # eval_satisfied → END（子图正常退出）
    # eval_retry → SkillScreening（回退重走）
    # eval_terminated → END（子图终止退出）
    graph.add_conditional_edges(
        DagExecutorSubGraphNodeName.STATE_EVALUATOR.value,
        route_by_eval,
        {
            DagEvalRoute.SATISFIED.value: END,
            DagEvalRoute.RETRY.value: DagExecutorSubGraphNodeName.SKILL_SCREENING.value,
            DagEvalRoute.TERMINATED.value: END,
        },
    )

    return graph.compile()


# ===========================================================================
# 节点 1: DagPlannerNode — Plan 生成节点（外层图）
# ===========================================================================


class DagPlannerNode:
    """Plan 生成节点 — LangGraph 子图节点。

    做什么：从 ChatWorkflowState 提取上下文，构建 DagEngineState，
           执行全局 Plan 生成，将结果写入 dag_state.dag_engine_state。
    为什么这样做：对应原 DagEngine.run() 中的 Phase 1 逻辑。
    """

    def __init__(
        self,
        plan_generation: PlanGenerationNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.plan_generation = plan_generation
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行全局 Plan 生成。"""
        chat_state = ChatWorkflowState.from_graph_state(state)
        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        dag_state = self._build_dag_state(chat_state)
        dag_state.workflow_state["dag_engine_started_at_ms"] = int(time.time() * 1000)

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
            dag_state = await self.plan_generation.execute(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
            )

            if not dag_state.plan.states:
                logger.warning(
                    f"[TraceID:{trace_id}] Plan 生成结果为空，跳过执行"
                )
                dag_state.terminated = True
                dag_state.termination_reason = "Plan 生成结果为空"

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
                                "responsibility": s.responsibility,
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
            logger.error(f"[TraceID:{trace_id}] Plan 生成异常: {exc}")
            dag_state.terminated = True
            dag_state.termination_reason = f"Plan 生成异常: {exc}"

        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
        return chat_state.as_graph_state()

    def _build_dag_state(self, chat_state: ChatWorkflowState) -> DagEngineState:
        """从 ChatWorkflowState 构建 DagEngineState。"""
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
# 节点 2: DagStateExecutorWrapper — Executor 子图包装器（外层图）
# ===========================================================================


class DagStateExecutorWrapper:
    """Executor 子图包装器 — LangGraph 外层图节点。

    做什么：在调用 Executor 子图前完成初始化（发布 State 启动事件、
           构建 DagExecutorRuntimeState），然后调用子图 ainvoke()，
           子图完成后将结果同步回 DagEngineState。
    为什么这样做：DagStateExecutorNode 拆解为子图后，需要一个包装器
                  负责子图前的初始化和子图后的结果同步。
    """

    def __init__(
        self,
        state_executor_subgraph: Any,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.state_executor_subgraph = state_executor_subgraph
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 外层图节点入口。

        做什么：
        1. 从图状态提取 DagEngineState
        2. 安全守卫（已终止/无待执行 State）
        3. 发布 State 启动事件
        4. 初始化 executor_runtime
        5. 调用子图 ainvoke()
        6. 同步结果到 DagEngineState
        7. 返回更新后的图状态
        """
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            logger.warning("ExecutorWrapper: dag_engine_state 为空，跳过")
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 安全守卫
        if dag_state.terminated or dag_state.cursor >= len(dag_state.plan.states):
            logger.info(
                f"[TraceID:{trace_id}] ExecutorWrapper: 已终止或无待执行 State，"
                f"terminated={dag_state.terminated}, "
                f"cursor={dag_state.cursor}, "
                f"states_count={len(dag_state.plan.states)}"
            )
            return _save_dag_state_to_graph(chat_state, dag_state)

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
                ChatStatusStage.DAG_STATE_EXECUTION, ChatStatusState.RUNNING,
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
                "responsibility": current_state.responsibility,
                "intent": current_state.intent,
                "goal": current_state.goal,
            },
            self.event_publisher,
        )

        # 初始化 executor_runtime
        _reset_executor_runtime(dag_state, current_state)

        # 写回初始化后的 dag_state
        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")

        try:
            # 调用 Executor 子图
            subgraph_result = await self.state_executor_subgraph.ainvoke(
                chat_state.as_graph_state()
            )

            # 从子图结果恢复 ChatWorkflowState
            chat_state = ChatWorkflowState.from_graph_state(subgraph_result)

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] Executor 子图执行异常: {exc}"
            )
            # 重新提取 dag_state（子图可能已部分修改）
            _, dag_state = _extract_dag_state_from_graph(chat_state.as_graph_state())
            if dag_state is None:
                dag_state = DagEngineState()
            dag_state.terminated = True
            dag_state.termination_reason = f"Executor 子图异常: {exc}"
            dag_state.termination_state_id = current_state.state_id
            chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")

        return chat_state.as_graph_state()


# ===========================================================================
# 节点 3: DagCursorRouterNode — Cursor 路由节点（外层图）
# ===========================================================================


class DagCursorRouterNode:
    """Cursor 路由节点 — LangGraph 子图节点。

    做什么：作为 LangGraph 子图的路由决策源节点。
    为什么这样做：LangGraph 条件边需要一个源节点作为路由起点。
    注意：此节点是 checkpoint 持久化点。
    """

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口（无操作，仅作为条件边源节点和 checkpoint 点）。"""
        return {}


# ===========================================================================
# 节点 4: DagPlanSummarizerNode — Plan 结果汇总节点（外层图）
# ===========================================================================


class DagPlanSummarizerNode:
    """Plan 结果汇总节点 — LangGraph 子图节点。

    做什么：执行 Plan 结果汇总，发布完成/终止事件，
           将汇总结果写回 ChatWorkflowState。
    为什么这样做：对应原 DagEngine.run() 中的 Phase 3 逻辑和 _apply_dag_result 逻辑。
    """

    def __init__(
        self,
        plan_summary: PlanResultSummaryNode,
        chat_status_publisher: ChatStatusPublisher,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        self.plan_summary = plan_summary
        self.chat_status_publisher = chat_status_publisher
        self.event_publisher = event_publisher

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 执行 Plan 结果汇总。"""
        chat_state, dag_state = _extract_dag_state_from_graph(state)
        if dag_state is None:
            logger.warning("Summarizer: dag_engine_state 为空")
            chat_state.dag_state.is_dag_active = True
            return chat_state.as_graph_state()

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id
        started_at_ms = dag_state.workflow_state.get("dag_engine_started_at_ms", 0)

        summary_result = None
        try:
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
            logger.error(f"[TraceID:{trace_id}] Plan 结果汇总异常: {exc}")
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

        # === 将 DAG 结果写回 ChatWorkflowState ===
        chat_state.dag_state.is_dag_active = True
        chat_state.dag_state.dag_engine_state = dag_state.model_dump(mode="json")
        chat_state.dag_state.disambiguated_text = dag_state.disambiguated_text
        chat_state.dag_state.unresolved_pronouns = dag_state.unresolved_pronouns

        summary = dag_state.plan_summary
        if summary:
            chat_state.dag_state.plan_summary_text = summary.get("overall_result", "")

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

        if summary and summary.get("overall_result"):
            chat_state.mcp_tool_state.execution_summary = summary.get("overall_result", "")

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
    gating_service: Any = None,
    snapshot_manager: Any = None,
):
    """构建 Plan + Cursor 子图。

    做什么：创建 4 节点 LangGraph 图：Planner → Executor → Router → Summary。
           其中 Executor 是一个嵌套子图，内部包含：
           SkillScreening → StepPlan → StepExecutor(循环) → StateEvaluator。
    为什么这样做：将原 DagEngine.run() 中的两层循环（State 循环 + Step 循环）
                  全部拆分为由 LangGraph 图结构驱动的迭代。
    返回:
        CompiledGraph: 编译后的子图，可被 DagEngineNode 作为 ainvoke 调用。
    """
    # --- 构建 Executor 内部子图 ---
    state_executor_subgraph = build_state_executor_subgraph(
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
        gating_service=gating_service,
        snapshot_manager=snapshot_manager,
    )

    graph = StateGraph(ChatWorkflowState)

    # --- 创建 4 个外层节点实例 ---
    planner = DagPlannerNode(
        plan_generation=plan_generation,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )
    executor_wrapper = DagStateExecutorWrapper(
        state_executor_subgraph=state_executor_subgraph,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )
    router = DagCursorRouterNode()
    summarizer = DagPlanSummarizerNode(
        plan_summary=plan_summary,
        chat_status_publisher=chat_status_publisher,
        event_publisher=event_publisher,
    )

    # --- 注册 4 个节点 ---
    graph.add_node(DagSubGraphNodeName.DAG_PLANNER.value, planner)
    graph.add_node(DagSubGraphNodeName.DAG_STATE_EXECUTOR.value, executor_wrapper)
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
