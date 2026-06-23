"""Phase 9 DAG 引擎 — Cursor 路由节点。

做什么：根据 cursor 和 plan.states 的长度决定下一步。
为什么这样做：LangGraph 的条件路由是静态定义的，
              但通过 cursor 值的动态变化实现循环。
"""

from __future__ import annotations

from app.logger import logger
from app.workflow.dag.types import DagCursorRoute, DagEngineState


def route_by_cursor(dag_state: DagEngineState) -> str:
    """Plan + Cursor 路由函数（核心路由逻辑）。

    做什么：根据 cursor 和 plan.states 的长度决定下一步。
    为什么这样做：LangGraph 的条件路由是静态定义的，
                  但通过 cursor 值的动态变化实现循环。
    输入: DagEngineState — 包含 plan、cursor、terminated 等核心状态。
    输出: str — 路由决策 "continue" / "complete" / "terminate"。
    边界条件: terminated 优先判断，其次 cursor 与 states 长度比较。
    异常行为: 无，所有字段都有默认值。
    """
    plan = dag_state.plan
    cursor = dag_state.cursor
    terminated = dag_state.terminated

    # 终止条件：评估失败或预算耗尽
    if terminated:
        logger.info(
            f"[TraceID:{dag_state.plan.trace_id}] Cursor 路由: 终止 "
            f"reason={dag_state.termination_reason}"
        )
        return DagCursorRoute.TERMINATE.value

    # 循环条件：还有未执行的 State
    if cursor < len(plan.states):
        logger.info(
            f"[TraceID:{dag_state.plan.trace_id}] Cursor 路由: 继续 "
            f"cursor={cursor}/{len(plan.states)}"
        )
        return DagCursorRoute.CONTINUE.value

    # 全部完成
    logger.info(
        f"[TraceID:{dag_state.plan.trace_id}] Cursor 路由: 全部完成 "
        f"total_states={len(plan.states)}"
    )
    return DagCursorRoute.COMPLETE.value


def route_by_cursor_from_graph_state(state: dict) -> str:
    """LangGraph 条件边路由函数 — 从图状态中提取 DagEngineState 并路由。

    做什么：从 LangGraph 的 ChatWorkflowState 字典中反序列化 DagEngineState，
           然后调用 route_by_cursor 完成路由决策。
    为什么这样做：LangGraph 条件边的路由函数签名为 (state: dict) -> str，
                  但 route_by_cursor 需要 DagEngineState 类型，需要一个适配层。
    输入: state — LangGraph 图状态字典（ChatWorkflowState 序列化）。
    输出: str — 路由决策 "continue" / "complete" / "terminate"。
    边界条件: dag_engine_state 为空字典时默认终止。
    异常行为: 反序列化失败时记录日志并终止。
    """
    from app.workflow.context import ChatWorkflowState

    try:
        chat_state = ChatWorkflowState.from_graph_state(state)
        dag_engine_data = chat_state.dag_state.dag_engine_state
        if not dag_engine_data:
            logger.warning("Cursor 路由: dag_engine_state 为空，默认终止")
            return DagCursorRoute.TERMINATE.value
        dag_engine_state = DagEngineState(**dag_engine_data)
        return route_by_cursor(dag_engine_state)
    except Exception as exc:
        logger.error(f"Cursor 路由: 从图状态提取 DagEngineState 失败: {exc}")
        return DagCursorRoute.TERMINATE.value


def route_by_step_cursor(state: dict) -> str:
    """Executor 子图 — Step Cursor 路由函数。

    做什么：根据 executor_runtime.step_cursor 和 steps 长度判断是否还有剩余 Step。
    为什么这样做：step_executor_node 执行完当前 Step 后，需要路由函数判断
                  是继续下一个 Step 还是进入 State 评估。
    输入: state — LangGraph 图状态字典（ChatWorkflowState 序列化）。
    输出: str — 路由决策 "next_step" / "all_done"。
    边界条件: executor_runtime 为空时默认 all_done。
    异常行为: 反序列化失败时记录日志并返回 all_done。
    """
    from app.workflow.constants import DagStepCursorRoute
    from app.workflow.context import ChatWorkflowState

    try:
        chat_state = ChatWorkflowState.from_graph_state(state)
        dag_engine_data = chat_state.dag_state.dag_engine_state
        if not dag_engine_data:
            return DagStepCursorRoute.ALL_DONE.value

        executor_rt = dag_engine_data.get("executor_runtime", {})
        if not executor_rt:
            return DagStepCursorRoute.ALL_DONE.value

        step_cursor = executor_rt.get("step_cursor", 0)
        steps = executor_rt.get("steps", [])

        if step_cursor < len(steps):
            logger.info(
                f"Step Cursor 路由: 继续下一步 "
                f"step_cursor={step_cursor}/{len(steps)}"
            )
            return DagStepCursorRoute.NEXT_STEP.value

        logger.info(
            f"Step Cursor 路由: 所有 Step 完成 total_steps={len(steps)}"
        )
        return DagStepCursorRoute.ALL_DONE.value

    except Exception as exc:
        logger.error(f"Step Cursor 路由异常: {exc}")
        return DagStepCursorRoute.ALL_DONE.value


def route_by_eval(state: dict) -> str:
    """Executor 子图 — State 评估路由函数。

    做什么：根据 State 评估结果和重试计数决定下一步。
    为什么这样做：state_evaluator_node 评估完成后，需要路由函数判断
                  是重走 skill 筛选还是结束子图。
    输入: state — LangGraph 图状态字典（ChatWorkflowState 序列化）。
    输出: str — 路由决策 "eval_satisfied" / "eval_retry" / "eval_terminated"。
    边界条件: executor_runtime 为空时默认 eval_terminated。
    异常行为: 反序列化失败时记录日志并返回 eval_terminated。
    """
    from app.workflow.constants import DagEvalRoute
    from app.workflow.context import ChatWorkflowState
    from app.workflow.dag.types import DagNodeStatus

    try:
        chat_state = ChatWorkflowState.from_graph_state(state)
        dag_engine_data = chat_state.dag_state.dag_engine_state
        if not dag_engine_data:
            return DagEvalRoute.TERMINATED.value

        executor_rt = dag_engine_data.get("executor_runtime", {})
        if not executor_rt:
            return DagEvalRoute.TERMINATED.value

        state_runtime = executor_rt.get("state_runtime", {})
        status = state_runtime.get("status", DagNodeStatus.PENDING.value)

        # 评估通过
        if status == DagNodeStatus.SUCCEEDED.value:
            logger.info("State 评估路由: 评估通过，子图结束")
            return DagEvalRoute.SATISFIED.value

        # 评估不通过：检查重试计数
        dag_state_data = DagEngineState(**dag_engine_data)
        if dag_state_data.plan_replan_count < 1:
            logger.info(
                f"State 评估路由: 评估不通过，重试 "
                f"replan_count={dag_state_data.plan_replan_count}"
            )
            return DagEvalRoute.RETRY.value

        # 已达重试上限
        logger.info(
            f"State 评估路由: 评估不通过且已达上限 "
            f"replan_count={dag_state_data.plan_replan_count}"
        )
        return DagEvalRoute.TERMINATED.value

    except Exception as exc:
        logger.error(f"State 评估路由异常: {exc}")
        return DagEvalRoute.TERMINATED.value
