"""Phase 9 DAG 引擎 — Cursor 路由节点。

做什么：根据 cursor 和 plan.states 的长度决定下一步。
为什么这样做：LangGraph 的条件路由是静态定义的，
              但通过 cursor 值的动态变化实现循环。
"""

from __future__ import annotations

from app.logger import logger
from app.workflow.dag.types import DagCursorRoute, DagEngineState


def route_by_cursor(dag_state: DagEngineState) -> str:
    """Plan + Cursor 路由函数。

    做什么：根据 cursor 和 plan.states 的长度决定下一步。
    为什么这样做：LangGraph 的条件路由是静态定义的，
                  但通过 cursor 值的动态变化实现循环。
    返回:
        str: 路由决策 — "continue" / "complete" / "terminate"。
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
