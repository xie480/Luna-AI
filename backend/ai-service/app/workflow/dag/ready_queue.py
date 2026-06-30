"""DAG ReadyQueue — 基于依赖拓扑的并行就绪队列。

做什么：根据 Step 的 dependencies（depends_on）字段计算当前可并行执行的步骤集合。
为什么这样做：替代 current_step_index 线性游标，支持 DAG 拓扑并行调度。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.workflow.dag.types import AgentStepState, StepStatusEnum


class ReadyQueue:
    """就绪队列 — 计算可并行执行的 Step。

    核心逻辑：
        1. 遍历所有 PENDING 状态的 Step
        2. 检查其 dependencies 中的每个前置 Step 是否已 PASSED
        3. 如果所有前置都已 PASSED，该 Step 进入 ready 集合
        4. ready 集合中的 Step 可通过 asyncio.gather 并行执行

    使用方式：
        ready_queue = ReadyQueue()
        ready_steps = ready_queue.compute_ready_steps(steps, completed_ids, running_ids)
    """

    def compute_ready_steps(
        self,
        steps: list[AgentStepState],
        completed_ids: set[str],
        running_ids: set[str],
    ) -> list[AgentStepState]:
        """计算当前可并行执行的步骤列表。

        做什么：从所有 PENDING 步骤中筛选出依赖已全部完成的步骤。
        为什么这样做：只有所有前置依赖都已完成的步骤才能安全并行执行，
                      确保 DAG 拓扑的执行顺序正确。

        参数:
            steps: 全局步骤列表（PlanState.steps）。
            completed_ids: 已完成的步骤 ID 集合（PlanState.completed_step_ids）。
            running_ids: 正在执行的步骤 ID 集合（PlanState.running_step_ids），
                        用于防重复调度。

        返回:
            可并行执行的 Step 列表（可能为空）。
        """
        ready: list[AgentStepState] = []

        for step in steps:
            # 只处理 PENDING 状态的步骤
            if step.status != StepStatusEnum.PENDING:
                continue

            # 排除已在运行中的步骤（防重复调度）
            if step.step_id in running_ids:
                continue

            # 检查依赖是否全部完成
            if not step.dependencies:
                # 无依赖的步骤直接进入就绪集合
                ready.append(step)
                continue

            # 有依赖：检查所有前置步骤是否已完成
            all_deps_met = all(
                dep_id in completed_ids for dep_id in step.dependencies
            )
            if all_deps_met:
                ready.append(step)

        if ready:
            logger.info(
                f"ReadyQueue: 计算就绪步骤完成, "
                f"ready_count={len(ready)}, "
                f"pending_count={sum(1 for s in steps if s.status == StepStatusEnum.PENDING)}, "
                f"running_count={len(running_ids)}, "
                f"completed_count={len(completed_ids)}"
            )

        return ready

    def mark_running(
        self,
        step: AgentStepState,
        running_ids: set[str],
    ) -> None:
        """标记 Step 为运行中。

        做什么：
        1. 将 step_id 加入 running_ids 集合
        2. 将 step.status 设为 RUNNING
        3. 记录开始时间戳

        参数:
            step: 要标记为运行中的步骤。
            running_ids: 正在执行的步骤 ID 集合（引用传递，直接修改）。
        """
        step.status = StepStatusEnum.RUNNING
        running_ids.add(step.step_id)

    def mark_completed(
        self,
        step: AgentStepState,
        completed_ids: set[str],
        running_ids: set[str],
    ) -> None:
        """标记 Step 为已完成。

        做什么：
        1. 将 step_id 从 running_ids 移除
        2. 将 step_id 加入 completed_ids 集合
        3. 将 step.status 设为 PASSED

        参数:
            step: 要标记为已完成的步骤。
            completed_ids: 已完成的步骤 ID 集合（引用传递，直接修改）。
            running_ids: 正在执行的步骤 ID 集合（引用传递，直接修改）。
        """
        step.status = StepStatusEnum.PASSED
        running_ids.discard(step.step_id)
        completed_ids.add(step.step_id)

    def mark_failed(
        self,
        step: AgentStepState,
        failed_ids: set[str],
        running_ids: set[str],
    ) -> None:
        """标记 Step 为失败。

        做什么：
        1. 将 step_id 从 running_ids 移除
        2. 将 step_id 加入 failed_ids 集合
        3. 将 step.status 设为 FAILED

        参数:
            step: 要标记为失败的步骤。
            failed_ids: 失败的步骤 ID 集合（引用传递，直接修改）。
            running_ids: 正在执行的步骤 ID 集合（引用传递，直接修改）。
        """
        step.status = StepStatusEnum.FAILED
        running_ids.discard(step.step_id)
        failed_ids.add(step.step_id)

    def is_all_done(
        self,
        steps: list[AgentStepState],
        completed_ids: set[str],
        failed_ids: set[str],
    ) -> bool:
        """判断所有 Step 是否已完成（PASSED 或 FAILED）。

        做什么：检查所有步骤是否都已达到终态。
        为什么这样做：当所有步骤完成时，可以安全退出 Step Loop 进入 FinalVerify。

        参数:
            steps: 全局步骤列表。
            completed_ids: 已完成的步骤 ID 集合。
            failed_ids: 失败的步骤 ID 集合。

        返回:
            True 表示所有步骤都已处于终态。
        """
        done_ids = completed_ids | failed_ids
        return len(done_ids) >= len(steps) if steps else True

    def compute_dag_stats(
        self,
        steps: list[AgentStepState],
        completed_ids: set[str],
        running_ids: set[str],
        failed_ids: set[str],
    ) -> dict[str, Any]:
        """计算 DAG 调度统计信息。

        做什么：统计当前 DAG 调度状态，供事件发布和日志记录使用。

        参数:
            steps: 全局步骤列表。
            completed_ids: 已完成的步骤 ID 集合。
            running_ids: 正在执行的步骤 ID 集合。
            failed_ids: 失败的步骤 ID 集合。

        返回:
            包含统计信息的字典。
        """
        return {
            "total": len(steps),
            "pending": sum(1 for s in steps if s.status == StepStatusEnum.PENDING),
            "running": len(running_ids),
            "completed": len(completed_ids),
            "failed": len(failed_ids),
        }
