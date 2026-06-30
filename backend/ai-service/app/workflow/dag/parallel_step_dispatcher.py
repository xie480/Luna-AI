"""并行步骤调度节点。

做什么：接收 ReadyQueue 输出的就绪步骤列表，通过 asyncio.gather 并行执行。
为什么这样做：替代原有的逐个 Step 串行执行模式，利用 DAG 拓扑实现并行加速。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.workflow.constants import (
    AgentStepLoopSubGraphNodeName,
    DagWorkflowEventType,
)
from app.workflow.dag.ready_queue import ReadyQueue
from app.workflow.dag.types import (
    AgentLoopState,
    AgentStepState,
    ExecutionState,
    StepEvaluationVerdict,
    StepStatusEnum,
)
from app.workflow.events import ChatWorkflowEventPublisher


async def _emit_dag_event(
    event_type: DagWorkflowEventType,
    trace_id: str,
    session_id: str,
    payload: dict[str, Any],
    event_publisher: ChatWorkflowEventPublisher | None,
) -> None:
    """发布 DAG 工作流事件到前端。"""
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
        logger.warning(f"ParallelDispatcher 事件发布失败: type={event_type.value}, error={exc}")


class ParallelStepDispatcherNode:
    """并行步骤调度节点。

    核心逻辑：
        1. 从 ReadyQueue 获取 ready_steps
        2. 标记所有 ready_steps 为 RUNNING
        3. 为每个 ready_step 构建独立的执行上下文
        4. 通过 asyncio.gather 并行执行所有 ready_step
        5. 收集结果，更新 PlanState（completed_step_ids / failed_step_ids）
        6. 发布并行执行事件
    """

    def __init__(
        self,
        step_execute_fn: Callable,
        chat_workflow_extractor: Callable,
        state_saver: Callable,
        event_publisher: ChatWorkflowEventPublisher | None = None,
    ):
        """初始化并行步骤调度节点。

        参数:
            step_execute_fn: 执行单个 Step 的完整 StepLoop 的异步函数。
                             签名: async fn(step, agent_loop, trace_id, session_id) -> dict
            chat_workflow_extractor: 从图 state 中提取 ChatWorkflowState 和 AgentLoopState 的函数。
            state_saver: 将 AgentLoopState 保存回图 state 的函数。
            event_publisher: 事件发布器实例。
        """
        self._step_execute_fn = step_execute_fn
        self._extract_agent_loop_state = chat_workflow_extractor
        self._save_agent_loop_state_to_graph = state_saver
        self.event_publisher = event_publisher
        self._ready_queue = ReadyQueue()

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph 节点入口 — 并行调度所有就绪步骤。

        做什么：
        1. 计算 ready_steps
        2. 并行执行：asyncio.gather(*[self._execute_step(s) for s in ready_steps])
        3. 汇总结果，更新 completed_step_ids / failed_step_ids
        4. 发布 EVT_DAG_PARALLEL_STEPS_DISPATCHED 事件
        """
        from app.workflow.context import ChatWorkflowState

        # 提取会话状态和 Agent Loop 状态
        chat_state: ChatWorkflowState = state.get("chat_workflow_state")
        if not chat_state:
            return state

        agent_loop: AgentLoopState | None = chat_state.dag_state.dag_engine_state
        if agent_loop is None:
            return state

        trace_id = chat_state.runtime.trace_id
        session_id = chat_state.runtime.session_id

        # 计算就绪步骤
        ready_steps = self._ready_queue.compute_ready_steps(
            steps=agent_loop.plan.steps,
            completed_ids=agent_loop.plan.completed_step_ids,
            running_ids=agent_loop.plan.running_step_ids,
        )

        if not ready_steps:
            # 没有就绪步骤，直接返回
            logger.info(
                f"[TraceID:{trace_id}] ParallelStepDispatcher: 无就绪步骤，跳过"
            )
            return self._save_state(chat_state, agent_loop)

        logger.info(
            f"[TraceID:{trace_id}] ParallelStepDispatcher: 调度 {len(ready_steps)} 个就绪步骤并行执行"
        )

        # 标记所有就绪步骤为 RUNNING
        for step in ready_steps:
            self._ready_queue.mark_running(step, agent_loop.plan.running_step_ids)

        # 保存状态（确保 running 状态已持久化）
        self._save_state(chat_state, agent_loop)

        # 发布并行调度事件
        dispatched_steps_data = [
            {
                "step_id": s.step_id,
                "title": s.title,
                "execution_mode": s.execution_mode,
            }
            for s in ready_steps
        ]
        stats = self._ready_queue.compute_dag_stats(
            agent_loop.plan.steps,
            agent_loop.plan.completed_step_ids,
            agent_loop.plan.running_step_ids,
            agent_loop.plan.failed_step_ids,
        )
        await _emit_dag_event(
            DagWorkflowEventType.EVT_DAG_PARALLEL_STEPS_DISPATCHED,
            trace_id, session_id,
            {
                "plan_id": agent_loop.goal.task_id,
                "dispatched_steps": dispatched_steps_data,
                "concurrency": len(ready_steps),
                "ready_queue_size": len(ready_steps),
                "pending_count": stats["pending"],
                "running_count": stats["running"],
                "completed_count": stats["completed"],
            },
            self.event_publisher,
        )

        # 并行执行所有就绪步骤
        results = await asyncio.gather(
            *[
                self._execute_single_step(
                    step=step,
                    agent_loop=agent_loop,
                    chat_state=chat_state,
                    trace_id=trace_id,
                    session_id=session_id,
                )
                for step in ready_steps
            ],
            return_exceptions=True,
        )

        # 汇总执行结果
        for step, result in zip(ready_steps, results):
            if isinstance(result, Exception):
                # 步骤执行异常
                logger.error(
                    f"[TraceID:{trace_id}] ParallelStepDispatcher: "
                    f"步骤 {step.step_id} ({step.title}) 执行异常: {result}"
                )
                self._ready_queue.mark_failed(
                    step,
                    agent_loop.plan.failed_step_ids,
                    agent_loop.plan.running_step_ids,
                )
                # 发布步骤失败事件
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_STEP_FAILED,
                    trace_id, session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "step_id": step.step_id,
                        "title": step.title,
                        "error": str(result),
                    },
                    self.event_publisher,
                )
            elif isinstance(result, dict) and result.get("success", False):
                # 步骤执行成功
                self._ready_queue.mark_completed(
                    step,
                    agent_loop.plan.completed_step_ids,
                    agent_loop.plan.running_step_ids,
                )
                # 保存步骤执行结果摘要
                step.result_summary = result.get("summary", "")
                step.completed_at_ms = int(time.time() * 1000)
                # 发布步骤完成事件
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_STEP_COMPLETED,
                    trace_id, session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "step_id": step.step_id,
                        "title": step.title,
                        "result_summary": step.result_summary[:200],
                    },
                    self.event_publisher,
                )
            else:
                # 步骤执行失败（工具失败等可重试场景）
                self._ready_queue.mark_failed(
                    step,
                    agent_loop.plan.failed_step_ids,
                    agent_loop.plan.running_step_ids,
                )
                error_msg = (
                    result.get("error", "步骤执行失败")
                    if isinstance(result, dict)
                    else "未知错误"
                )
                # 发布步骤失败事件
                await _emit_dag_event(
                    DagWorkflowEventType.EVT_DAG_STEP_FAILED,
                    trace_id, session_id,
                    {
                        "plan_id": agent_loop.goal.task_id,
                        "step_id": step.step_id,
                        "title": step.title,
                        "error": error_msg,
                    },
                    self.event_publisher,
                )

        # 检查是否有就绪的依赖 Step 可以触发
        # 当并行步骤完成后，可能有新的 Step 依赖已满足，下次 StepRouter 会重新计算
        stats_after = self._ready_queue.compute_dag_stats(
            agent_loop.plan.steps,
            agent_loop.plan.completed_step_ids,
            agent_loop.plan.running_step_ids,
            agent_loop.plan.failed_step_ids,
        )
        logger.info(
            f"[TraceID:{trace_id}] ParallelStepDispatcher: 调度完成, "
            f"total={stats_after['total']}, completed={stats_after['completed']}, "
            f"running={stats_after['running']}, failed={stats_after['failed']}, "
            f"pending={stats_after['pending']}"
        )

        # 保存最终状态
        return self._save_state(chat_state, agent_loop)

    async def _execute_single_step(
        self,
        step: AgentStepState,
        agent_loop: AgentLoopState,
        chat_state: Any,
        trace_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """执行单个 Step 的完整 StepLoop。

        做什么：
        1. 设置当前步骤上下文（current_step_id, partitioned_outputs 等）
        2. 调用 _step_execute_fn 执行 Step 的 Think → Execute → Observe → Evaluate
        3. 返回执行结果（pass/fail 等）

        参数:
            step: 要执行的步骤。
            agent_loop: Agent Loop 引擎全局状态（深拷贝避免竞争）。
            chat_state: ChatWorkflowState 引用。
            trace_id: 追踪 ID。
            session_id: 会话 ID。

        返回:
            {
                "success": bool,
                "verdict": "pass" | "fail" | "needs_replan",
                "summary": str,
                "error": str (可选),
            }
        """
        step.started_at_ms = int(time.time() * 1000)

        # 设置 ExecutionState 的当前步骤上下文
        agent_loop.execution = ExecutionState()
        agent_loop.execution.current_step_id = step.step_id

        try:
            # 调用外部传入的步骤执行函数
            result = await self._step_execute_fn(
                step=step,
                agent_loop=agent_loop,
                chat_state=chat_state,
                trace_id=trace_id,
                session_id=session_id,
            )

            # 解析执行结果
            verdict = result.get("verdict", StepEvaluationVerdict.PASS.value)

            if verdict == StepEvaluationVerdict.PASS.value:
                # 步骤通过
                return {
                    "success": True,
                    "verdict": verdict,
                    "summary": agent_loop.execution.last_observation
                        if agent_loop.execution.last_observation
                        else step.expected_output,
                }
            else:
                # 步骤未通过（fail / needs_replan）
                return {
                    "success": False,
                    "verdict": verdict,
                    "error": result.get("error", f"步骤评估结果: {verdict}"),
                    "summary": "",
                }

        except Exception as exc:
            logger.error(
                f"[TraceID:{trace_id}] ParallelStepDispatcher: "
                f"步骤 {step.step_id} 执行异常: {exc}"
            )
            return {
                "success": False,
                "verdict": "fail",
                "error": str(exc),
                "summary": "",
            }

    def _save_state(self, chat_state: Any, agent_loop: AgentLoopState) -> dict[str, Any]:
        """将 AgentLoopState 保存回 LangGraph 状态。

        参数:
            chat_state: ChatWorkflowState 实例。
            agent_loop: AgentLoopState 实例。

        返回:
            更新后的 LangGraph state 字典。
        """
        chat_state.dag_state.dag_engine_state = agent_loop.model_dump(mode="json")
        return chat_state.as_graph_state()
