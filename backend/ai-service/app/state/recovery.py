"""
Luna AI 恢复协调器 — 中断后的恢复协调逻辑。

做什么：提供从检查点或快照恢复任务的能力，
        处理 Gating 审批恢复和情绪冻结恢复。
为什么这样做：恢复逻辑涉及多种中断类型，需要统一协调入口。
边界条件：恢复失败时返回 failure 结果，不抛异常。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.logger import logger
from app.state.task_state_machine import TaskStatus


class RecoveryResult(BaseModel):
    """恢复结果。

    做什么：封装从检查点/快照恢复的结果信息。
    为什么这样做：统一恢复返回值结构，避免 None 检查和类型判断。

    参数:
        success: 恢复是否成功。
        dag_state: 恢复后的 DAG 引擎状态（序列化字典）。
        task_status: 恢复后的任务状态。
        reason: 恢复原因/描述。
        recovered_cursor: 恢复后的 cursor 位置。
        recovered_snapshot_version: 恢复的快照版本号。
    """

    success: bool = False
    dag_state: dict[str, Any] | None = None
    task_status: TaskStatus = TaskStatus.FAILED
    reason: str = ""
    recovered_cursor: int = 0
    recovered_snapshot_version: int = 0


class RecoveryCoordinator:
    """恢复协调器 — 中断后的恢复协调逻辑。

    做什么：提供从检查点或快照恢复任务的能力，
            处理 Gating 审批恢复和情绪冻结恢复。
    为什么这样做：恢复逻辑涉及多种中断类型，需要统一协调入口。
    输入输出：
        - recover_task(): 返回 RecoveryResult。
        - resume_after_gating(): 返回 RecoveryResult。
        - resume_after_freeze(): 返回 RecoveryResult。
    边界条件：恢复失败时返回 failure 结果，不抛异常。
    """

    def __init__(
        self,
        snapshot_manager: Any = None,
        checkpoint_manager: Any = None,
    ):
        """初始化恢复协调器。

        参数:
            snapshot_manager: SnapshotManager 实例。
            checkpoint_manager: ParallelCheckpointManager 实例（可选）。
        """
        self._snap_mgr = snapshot_manager
        self._ckpt_mgr = checkpoint_manager

    async def recover_task(
        self,
        task_id: str,
    ) -> RecoveryResult:
        """从检查点或快照恢复任务。

        恢复流程：
        1. 尝试从 SnapshotManager 加载最新快照
        2. 如果快照不存在，返回失败（任务无法恢复）

        恢复后的操作：
        - 重置所有 RUNNING 状态的 Step/State 为 PENDING
        - 如果 gating_suspended=True，记录警告
        - 返回恢复后的 DagEngineState

        参数:
            task_id: 任务 ID。

        返回:
            RecoveryResult：success=True 时 dag_state 为恢复后的状态字典。
        """
        # 1. 从快照管理器加载最新快照
        dag_state = None
        snapshot_version = 0
        use_pg = False

        if self._snap_mgr is not None:
            dag_state = await self._snap_mgr.load_latest_snapshot(task_id)

        if dag_state is None:
            return RecoveryResult(
                success=False,
                reason="无可用快照或检查点",
                task_status=TaskStatus.FAILED,
            )

        # 如果是字符串（JSON），解析为字典
        if isinstance(dag_state, str):
            import json
            try:
                dag_state = json.loads(dag_state)
            except json.JSONDecodeError as exc:
                return RecoveryResult(
                    success=False,
                    reason=f"快照 JSON 解析失败: {exc}",
                    task_status=TaskStatus.FAILED,
                )

        # 确保是字典
        if not isinstance(dag_state, dict):
            return RecoveryResult(
                success=False,
                reason=f"快照格式异常: 期望 dict, 实际 {type(dag_state).__name__}",
                task_status=TaskStatus.FAILED,
            )

        # 2. 重置 RUNNING 状态的 State 为 PENDING
        state_runtimes: dict = dag_state.get("state_runtimes", {})
        for state_id, runtime in state_runtimes.items():
            if isinstance(runtime, dict) and runtime.get("status") == "RUNNING":
                runtime["status"] = "PENDING"
                logger.info(
                    f"RecoveryCoordinator: 重置 State 状态 "
                    f"state_id={state_id}, PENDING -> 原 RUNNING"
                )

        # 3. 重置 executor_runtime 中的 RUNNING 标志
        executor_runtime: dict = dag_state.get("executor_runtime", {})
        if executor_runtime:
            state_rt = executor_runtime.get("state_runtime", {})
            if isinstance(state_rt, dict):
                if state_rt.get("status") == "RUNNING":
                    state_rt["status"] = "PENDING"
                    state_rt["steps_completed"] = 0
                    state_rt["nodes_succeeded"] = 0
                    state_rt["nodes_failed"] = 0
                    logger.info(
                        "RecoveryCoordinator: 重置 executor_runtime 状态为 PENDING"
                    )

        # 4. 清除终止标志（如果之前是因中断而非失败而终止）
        dag_state["terminated"] = False
        dag_state["termination_reason"] = ""

        # 5. 如果存在 gating_suspended，记录警告
        if dag_state.get("gating_suspended", False):
            logger.warning(
                f"RecoveryCoordinator: 恢复时检测到 Gating 挂起状态 "
                f"task={task_id}, pending_nodes={dag_state.get('gating_pending_node_ids', [])}"
            )

        cursor = dag_state.get("cursor", 0)
        states = dag_state.get("plan", {}).get("states", [])
        completed_states = len([s for s in states[:cursor]])

        logger.info(
            f"RecoveryCoordinator: 恢复成功 "
            f"task={task_id}, cursor={cursor}, "
            f"已完成的 State 数={completed_states}"
        )

        return RecoveryResult(
            success=True,
            dag_state=dag_state,
            task_status=TaskStatus.RECOVERING,
            reason=(
                f"从快照恢复成功，cursor={cursor}，"
                f"已完成的 State 数={completed_states}"
            ),
            recovered_cursor=cursor,
            recovered_snapshot_version=snapshot_version,
        )

    async def resume_after_gating(
        self,
        task_id: str,
        dag_state: dict[str, Any],
        approval_result: dict[str, Any],
    ) -> RecoveryResult:
        """Gating 审批结束后恢复执行。

        做什么：
        - 从 gating_suspended 恢复 DagEngineState
        - 注入用户审批结果到 step_context
        - 清除 gating_suspended 标志
        - 返回恢复后的状态

        参数:
            task_id: 任务 ID。
            dag_state: 当前 DAG 引擎状态字典。
            approval_result: 用户审批结果字典，包含：
                - audit_log_id: 审批记录 ID
                - approved: 是否同意
                - user_feedback: 用户反馈文字

        返回:
            RecoveryResult：success=True 时 dag_state 为更新后的状态。
        """
        if not dag_state.get("gating_suspended", False):
            return RecoveryResult(
                success=False,
                reason="任务未处于 Gating 挂起状态",
                task_status=TaskStatus.GATING_SUSPENDED,
            )

        # 注入审批结果
        pending_ids = dag_state.get("gating_pending_node_ids", [])
        for nid in pending_ids:
            logger.info(
                f"RecoveryCoordinator: 注入 Gating 审批结果 "
                f"task={task_id}, node={nid}, "
                f"approved={approval_result.get('approved')}"
            )

        # 清除挂起标志
        dag_state["gating_suspended"] = False

        # 将审批结果注入到 executor_runtime 中
        executor_runtime = dag_state.get("executor_runtime", {})
        if isinstance(executor_runtime, dict):
            step_context = executor_runtime.get("step_context", {})
            if isinstance(step_context, dict):
                step_context["gating_approval_result"] = approval_result
            executor_runtime["step_context"] = step_context
            dag_state["executor_runtime"] = executor_runtime

        return RecoveryResult(
            success=True,
            dag_state=dag_state,
            task_status=TaskStatus.RUNNING,
            reason="Gating 审批完成，已恢复执行",
            recovered_cursor=dag_state.get("cursor", 0),
        )

    async def resume_after_freeze(
        self,
        task_id: str,
    ) -> RecoveryResult:
        """情绪冻结后恢复执行。

        做什么：
        - 从 Redis 加载情绪冻结快照
        - 恢复 DagEngineState
        - 清除冻结标志
        - 返回恢复后的状态

        参数:
            task_id: 任务 ID。

        返回:
            RecoveryResult：success=True 时 dag_state 为恢复后的状态。
        """
        if self._snap_mgr is None:
            return RecoveryResult(
                success=False,
                reason="SnapshotManager 未初始化",
            )

        # 1. 加载冻结快照
        freeze_data = await self._snap_mgr.load_freeze_snapshot(task_id)
        if freeze_data is None:
            return RecoveryResult(
                success=False,
                reason="无情绪冻结快照",
                task_status=TaskStatus.PAUSED,
            )

        dag_state_json = freeze_data.get("dag_state_json")
        if not dag_state_json:
            return RecoveryResult(
                success=False,
                reason="情绪冻结快照中缺少 dag_state_json",
            )

        # 如果是字符串，解析为字典
        if isinstance(dag_state_json, str):
            import json
            try:
                dag_state = json.loads(dag_state_json)
            except json.JSONDecodeError as exc:
                return RecoveryResult(
                    success=False,
                    reason=f"冻结快照 JSON 解析失败: {exc}",
                )
        else:
            dag_state = dag_state_json

        # 2. 清除终止标志
        dag_state["terminated"] = False
        dag_state["termination_reason"] = ""

        # 3. 清除 gating_suspended 标志（如果有）
        dag_state["gating_suspended"] = False

        esm_before = freeze_data.get("esm_before", "UNKNOWN")

        # 4. 删除冻结快照（防止重复恢复）
        await self._snap_mgr.delete_freeze_snapshot(task_id)

        logger.info(
            f"RecoveryCoordinator: 情绪冻结恢复成功 "
            f"task={task_id}, esm_before={esm_before}"
        )

        return RecoveryResult(
            success=True,
            dag_state=dag_state,
            task_status=TaskStatus.RUNNING,
            reason=f"情绪冻结恢复成功，冻结前情绪={esm_before}",
            recovered_cursor=dag_state.get("cursor", 0),
        )
