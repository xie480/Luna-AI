"""Phase 9 DAG 引擎 — Plan + Cursor 循环引擎。

做什么：实现 Plan + Cursor 模式的 DAG 引擎，将 for 循环的数据放进 State，
        而不是把 for 循环的代码写进 Node。
为什么这样做：LangGraph 图中只有固定的节点，但通过 cursor 值的动态变化
              实现任意长度的 State 序列执行。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.chat_status import ChatStatusPublisher
from app.api.chat_status_texts import get_chat_status_text
from app.logger import logger
from app.types.constants import ChatStatusStage, ChatStatusState
from app.workflow.dag.budget import BudgetTracker
from app.workflow.dag.evaluation import StateResultCompressor
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
    DagNodeStatus,
    GlobalBudget,
    PlanSummaryResult,
    ReplanContext,
    StateBudget,
    StateEvaluationResult,
    StateRuntimeState,
    TerminationContext,
)


class DagEngine:
    """DAG 引擎 — Plan + Cursor 循环调度核心。

    做什么：编排全局 Plan 生成、State 执行、评估、重构、汇总的完整流程。
    为什么这样做：将 for 循环的数据放进 State，LangGraph 看到的是"固定图 + 动态路由"。
    """

    def __init__(
        self,
        prompt_manager: Any,
        llm_client: Any,
        mcp_tool_registry: Any,
        memory_manager: Any,
        rag_orchestrator: Any,
        chat_status_publisher: ChatStatusPublisher | None = None,
    ):
        """初始化 DAG 引擎。

        参数:
            prompt_manager: Prompt 管理器。
            llm_client: LLM 客户端。
            mcp_tool_registry: MCP 工具注册中心。
            memory_manager: 记忆管理器。
            rag_orchestrator: RAG 检索编排器。
            chat_status_publisher: Chat 状态发布器。
        """
        self.chat_status_publisher = chat_status_publisher or ChatStatusPublisher()

        # 初始化各子节点
        self.plan_generation = PlanGenerationNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.skill_screening = SkillScreeningNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.step_plan = StepPlanNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.step_executor = StepExecutor(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            mcp_tool_registry=mcp_tool_registry,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.step_retry = StepRetryPolicy(self.step_executor)
        self.step_merge = StepMergeNode(
            chat_status_publisher=self.chat_status_publisher,
        )
        self.state_evaluation = StateEvaluationNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.state_compressor = StateResultCompressor(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
        )
        self.plan_replan = PlanReplanNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )
        self.plan_summary = PlanResultSummaryNode(
            prompt_manager=prompt_manager,
            llm_client=llm_client,
            chat_status_publisher=self.chat_status_publisher,
        )

        # 依赖注入到 state_context
        self._memory_manager = memory_manager
        self._rag_orchestrator = rag_orchestrator
        self._mcp_tool_registry = mcp_tool_registry

    async def run(
        self,
        trace_id: str,
        session_id: str,
        dag_state: DagEngineState,
    ) -> DagEngineState:
        """执行 DAG 引擎的完整流程。

        做什么：
        1. 全局 Plan 生成
        2. Plan + Cursor 循环（State 执行 -> 评估 -> 重构）
        3. Plan 结果汇总
        4. 将汇总结果写入 dag_state

        返回:
            DagEngineState: 更新后的 DAG 引擎状态。
        """
        started_at_ms = int(time.time() * 1000)

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

            # 如果 Plan 为空，直接返回
            if not dag_state.plan.states:
                logger.warning(
                    f"[TraceID:{trace_id}] Plan 生成结果为空，跳过执行"
                )
                dag_state.terminated = True
                dag_state.termination_reason = "Plan 生成结果为空"

            # ============================================================
            # Phase 2: Plan + Cursor 循环
            # ============================================================
            budget_tracker = BudgetTracker(
                state_budget=StateBudget(),
                global_budget=dag_state.plan.global_budget,
                trace_id=trace_id,
            )

            while not dag_state.terminated and dag_state.cursor < len(dag_state.plan.states):
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

                # 初始化 State 运行时
                state_runtime = StateRuntimeState(
                    state_id=current_state.state_id,
                    status=DagNodeStatus.RUNNING,
                    intent=current_state.intent,
                    goal=current_state.goal,
                )
                budget_tracker.reset_state_budget()

                # 构建 state_context
                state_context = self._build_state_context(
                    dag_state=dag_state,
                    current_state=current_state,
                    budget_tracker=budget_tracker,
                    session_id=session_id,
                )

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
                    break

                # --- 逐 Step 执行 ---
                all_partitioned_outputs: dict[str, dict[str, Any]] = {}
                for step in steps:
                    # 检查预算
                    if budget_tracker.is_state_budget_exhausted():
                        logger.warning(
                            f"[TraceID:{trace_id}] State 预算耗尽，"
                            f"跳过剩余 Step"
                        )
                        state_runtime.budget_exhausted = True
                        break

                    if budget_tracker.is_global_budget_exhausted():
                        logger.warning(
                            f"[TraceID:{trace_id}] Plan 全局预算耗尽，"
                            f"终止引擎"
                        )
                        dag_state.terminated = True
                        dag_state.termination_reason = "Plan 全局预算耗尽"
                        dag_state.termination_state_id = current_state.state_id
                        break

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

                    # 统计成功/失败节点
                    for nid, out in step_outputs.items():
                        if out.get("success", True):
                            state_runtime.nodes_succeeded += 1
                        else:
                            state_runtime.nodes_failed += 1

                if dag_state.terminated:
                    break

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
                            state_runtime=state_runtime.model_dump(),
                            evaluation_result=eval_result.model_dump(),
                        )

                        # 构建重构上下文
                        replan_context = self._build_replan_context(
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

                        # 重构后 cursor 不变，重新执行当前 State
                        state_runtime.status = DagNodeStatus.DEGRADED
                        dag_state.state_runtimes[current_state.state_id] = (
                            state_runtime.model_dump()
                        )
                        # 不推进 cursor，下一轮循环重新执行
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

            # ============================================================
            # Phase 3: Plan 结果汇总
            # ============================================================
            summary_result = await self.plan_summary.execute(
                trace_id=trace_id,
                session_id=session_id,
                dag_state=dag_state,
            )

            dag_state.plan_summary = summary_result.model_dump()

            elapsed_ms = int(time.time() * 1000) - started_at_ms
            logger.info(
                f"[TraceID:{trace_id}] DAG 引擎执行完成: "
                f"states={len(dag_state.plan.states)}, "
                f"cursor={dag_state.cursor}, "
                f"terminated={dag_state.terminated}, "
                f"elapsed_ms={elapsed_ms}"
            )

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

        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] DAG 引擎执行异常: {e}")
            dag_state.terminated = True
            dag_state.termination_reason = f"引擎异常: {e}"

        return dag_state

    def _build_state_context(
        self,
        dag_state: DagEngineState,
        current_state: Any,
        budget_tracker: BudgetTracker,
        session_id: str,
    ) -> dict[str, Any]:
        """构建 State 执行上下文。

        做什么：将 DAG 引擎的状态注入到 state_context 中，
               供各原子节点执行时读取。
        """
        return {
            "session_id": session_id,
            "user_id": dag_state.workflow_state.get("runtime", {}).get(
                "user_id", "local_default_user"
            ),
            "trace_id": dag_state.plan.trace_id,
            "state_goal": current_state.goal,
            "state_intent": current_state.intent,
            "skill_registry": self._mcp_tool_registry,
            "memory_manager": self._memory_manager,
            "rag_orchestrator": self._rag_orchestrator,
            "disambiguated_text": dag_state.disambiguated_text,
            "session_context": dag_state.session_context,
            "user_profile": dag_state.user_profile,
            "memory_context": dag_state.memory_context,
            "partitioned_outputs": {},
            "current_step_context": {},
            "steps_total": 0,
        }

    def _build_replan_context(
        self,
        dag_state: DagEngineState,
        current_state: Any,
        state_runtime: StateRuntimeState,
        eval_result: StateEvaluationResult,
        compressed_result: str,
    ) -> ReplanContext:
        """构建 Plan 重构上下文。"""
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
