"""
Luna AI 任务状态机模块 — 任务级生命周期管理。

做什么：定义任务级状态枚举 TaskStatus，并提供 TaskStateMachine 类管理状态跃迁逻辑。
为什么这样做：与 DagNodeStatus（节点/State 级）分离，形成 Plan 级与节点级的双层状态管理体系。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.logger import logger


class TaskStatus(str, Enum):
    """任务级生命周期状态枚举。

    做什么：定义整个 Plan 级别的生命周期状态，涵盖创建、执行、暂停、中断、恢复、终止等全部阶段。
    为什么这样做：与 DagNodeStatus（节点/State 级）分离，形成 Plan 级与节点级的双层状态管理体系。
    输入输出：用于标记任务快照、控制任务跃迁、判断任务是否可恢复。
    边界条件：TERMINATED/TIMED_OUT/BUDGET_EXHAUSTED/FAILED 为不可恢复终态。
    异常行为：终态不允许再跃迁到任何非终态。
    """

    # === 创建态 ===
    CREATED = "CREATED"                          # 任务刚创建，未开始执行
    PLANNING = "PLANNING"                        # Plan 生成中
    PLAN_READY = "PLAN_READY"                    # Plan 已就绪

    # === 执行态 ===
    RUNNING = "RUNNING"                          # 任务执行中
    PAUSED = "PAUSED"                            # 任务暂停（用户手动或情绪冻结）
    PENDING_APPROVAL = "PENDING_APPROVAL"        # 等待审批
    DEGRADED = "DEGRADED"                        # 降级态（重规划中）
    GATING_SUSPENDED = "GATING_SUSPENDED"        # Gating 审批挂起

    # === 终态 ===
    SUCCEEDED = "SUCCEEDED"                      # 全部成功
    FAILED = "FAILED"                            # 不可恢复失败
    TERMINATED = "TERMINATED"                    # 手动终止
    TIMED_OUT = "TIMED_OUT"                      # 超时终止
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"        # 预算耗尽

    # === 恢复态 ===
    RECOVERING = "RECOVERING"                    # 正在从检查点恢复
    SNAPSHOT_RESTORED = "SNAPSHOT_RESTORED"      # 快照已还原


class TaskStateMachine:
    """任务状态机 — 管理任务级状态跃迁与校验。

    做什么：提供 TaskStatus 状态跃迁的合法性校验、状态转换执行和日志记录。
    为什么这样做：所有状态跃迁集中管理，防止非法跃迁导致状态不一致。
    输入输出：
        - transition(): 执行状态跃迁，返回 (success, message)。
        - can_transition(): 判断跃迁是否合法。
        - is_terminal(): 判断是否为终态。
    边界条件：终态禁止跃迁到非终态；非法跃迁返回 False 而非抛异常。
    异常行为：无。
    """

    # 状态跃迁规则表：{(from_status, to_status): trigger, ...}
    # 格式：from -> to : trigger（触发原因）
    _TRANSITIONS: dict[tuple[TaskStatus, TaskStatus], str] = {
        # 创建态 -> 执行/终态
        (TaskStatus.CREATED, TaskStatus.PLANNING): "开始规划",
        (TaskStatus.CREATED, TaskStatus.TERMINATED): "手动终止",

        # 规划态 -> 就绪/终态
        (TaskStatus.PLANNING, TaskStatus.PLAN_READY): "Plan 生成完成",
        (TaskStatus.PLANNING, TaskStatus.FAILED): "Plan 生成失败",
        (TaskStatus.PLANNING, TaskStatus.TERMINATED): "手动终止",

        # 就绪态 -> 执行/终态
        (TaskStatus.PLAN_READY, TaskStatus.RUNNING): "开始执行",
        (TaskStatus.PLAN_READY, TaskStatus.TERMINATED): "手动终止",

        # 执行态 -> 挂起/终态
        (TaskStatus.RUNNING, TaskStatus.PAUSED): "用户暂停 / 情绪冻结",
        (TaskStatus.RUNNING, TaskStatus.PENDING_APPROVAL): "高危工具审批",
        (TaskStatus.RUNNING, TaskStatus.GATING_SUSPENDED): "Gating 审批挂起",
        (TaskStatus.RUNNING, TaskStatus.DEGRADED): "State 评估不通过",
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED): "全部 State 完成",
        (TaskStatus.RUNNING, TaskStatus.FAILED): "不可恢复错误",
        (TaskStatus.RUNNING, TaskStatus.TIMED_OUT): "超时",
        (TaskStatus.RUNNING, TaskStatus.BUDGET_EXHAUSTED): "预算耗尽",
        (TaskStatus.RUNNING, TaskStatus.TERMINATED): "手动终止",

        # 暂停态 -> 恢复/终态
        (TaskStatus.PAUSED, TaskStatus.RUNNING): "用户恢复 / 情绪恢复",
        (TaskStatus.PAUSED, TaskStatus.TERMINATED): "手动终止",

        # 审批态 -> 恢复/终态
        (TaskStatus.PENDING_APPROVAL, TaskStatus.RUNNING): "用户同意",
        (TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED): "用户拒绝",
        (TaskStatus.PENDING_APPROVAL, TaskStatus.TERMINATED): "手动终止",

        # Gating 挂起态 -> 恢复/终态
        (TaskStatus.GATING_SUSPENDED, TaskStatus.RUNNING): "审批完成恢复",
        (TaskStatus.GATING_SUSPENDED, TaskStatus.FAILED): "审批拒绝",
        (TaskStatus.GATING_SUSPENDED, TaskStatus.TERMINATED): "手动终止",

        # 降级态 -> 恢复/终态
        (TaskStatus.DEGRADED, TaskStatus.RUNNING): "重规划完成",
        (TaskStatus.DEGRADED, TaskStatus.FAILED): "重规划失败",
        (TaskStatus.DEGRADED, TaskStatus.TERMINATED): "手动终止",

        # 恢复态 -> 执行/终态
        (TaskStatus.RECOVERING, TaskStatus.RUNNING): "恢复完成",
        (TaskStatus.RECOVERING, TaskStatus.FAILED): "恢复失败",

        # 快照还原态 -> 执行
        (TaskStatus.SNAPSHOT_RESTORED, TaskStatus.RUNNING): "从快照继续执行",
    }

    # 终态列表 — 不可从此类状态跃迁出去
    _TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.TERMINATED,
        TaskStatus.TIMED_OUT,
        TaskStatus.BUDGET_EXHAUSTED,
    })

    @classmethod
    def can_transition(
        cls,
        current: TaskStatus | str,
        target: TaskStatus | str,
    ) -> bool:
        """判断状态跃迁是否合法。

        做什么：检查从 current 到 target 的状态跃迁是否在规则表中定义。
        为什么这样做：防止非法的状态跳转，确保状态机一致性。

        参数:
            current: 当前状态（TaskStatus 枚举值或字符串）。
            target: 目标状态（TaskStatus 枚举值或字符串）。

        返回:
            True 表示跃迁合法，False 表示非法跃迁。
        """
        if isinstance(current, str):
            try:
                current = TaskStatus(current)
            except ValueError:
                return False
        if isinstance(target, str):
            try:
                target = TaskStatus(target)
            except ValueError:
                return False

        # 终态禁止跃迁
        if current in cls._TERMINAL_STATUSES:
            return False

        return (current, target) in cls._TRANSITIONS

    @classmethod
    def transition(
        cls,
        current: TaskStatus | str,
        target: TaskStatus | str,
        trace_id: str = "",
        task_id: str = "",
    ) -> tuple[bool, str]:
        """执行状态跃迁。

        做什么：检查跃迁合法性，记录跃迁日志，返回跃迁结果。
        为什么这样做：统一的状态变更入口，确保所有跃迁都被记录。

        参数:
            current: 当前状态。
            target: 目标状态。
            trace_id: 追踪 ID（可选）。
            task_id: 任务 ID（可选）。

        返回:
            (success, message)：成功或失败及其原因。
        """
        # 统一转为枚举
        if isinstance(current, str):
            try:
                current_enum = TaskStatus(current)
            except ValueError:
                return False, f"未知的当前状态: {current}"
        else:
            current_enum = current

        if isinstance(target, str):
            try:
                target_enum = TaskStatus(target)
            except ValueError:
                return False, f"未知的目标状态: {target}"
        else:
            target_enum = target

        # 如果状态相同，直接返回成功（不记录日志，避免噪声）
        if current_enum == target_enum:
            return True, "状态未变更"

        # 检查跃迁合法性
        if not cls.can_transition(current_enum, target_enum):
            reason = f"非法状态跃迁: {current_enum.value} -> {target_enum.value}"
            logger.warning(
                f"TaskStateMachine: {reason} "
                f"[TraceID:{trace_id}] [TaskID:{task_id}]"
            )
            return False, reason

        # 记录成功跃迁
        trigger = cls._TRANSITIONS.get((current_enum, target_enum), "未知触发")
        logger.info(
            f"TaskStateMachine: 状态跃迁 "
            f"{current_enum.value} -> {target_enum.value} "
            f"trigger={trigger} "
            f"[TraceID:{trace_id}] [TaskID:{task_id}]"
        )

        return True, trigger

    @classmethod
    def is_terminal(cls, status: TaskStatus | str) -> bool:
        """判断是否为终态。

        做什么：检查给定状态是否为不可恢复的终态。
        为什么这样做：终态判断用于决定任务是否可以继续或恢复。

        参数:
            status: 待检查的状态。

        返回:
            True 表示为终态，不可继续执行。
        """
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                return False
        return status in cls._TERMINAL_STATUSES

    @classmethod
    def get_next_allowed_states(cls, current: TaskStatus | str) -> list[TaskStatus]:
        """获取当前状态下允许跃迁到的所有目标状态。

        做什么：列出从当前状态可合法跃迁的所有目标状态。
        为什么这样做：用于 API 层校验外部输入、前端提示可执行操作。

        参数:
            current: 当前状态。

        返回:
            合法目标状态列表。终态返回空列表。
        """
        if isinstance(current, str):
            try:
                current = TaskStatus(current)
            except ValueError:
                return []

        if current in cls._TERMINAL_STATUSES:
            return []

        return [
            to_status
            for (from_status, to_status) in cls._TRANSITIONS
            if from_status == current
        ]

    @classmethod
    def get_trigger_reason(
        cls,
        current: TaskStatus | str,
        target: TaskStatus | str,
    ) -> str:
        """获取状态跃迁的触发原因描述。

        做什么：从规则表中查询 from->to 对应的触发原因字符串。

        参数:
            current: 当前状态。
            target: 目标状态。

        返回:
            触发原因描述，如 "用户暂停 / 情绪冻结"。
            如果跃迁不在规则表中，返回空字符串。
        """
        if isinstance(current, str):
            try:
                current = TaskStatus(current)
            except ValueError:
                return ""
        if isinstance(target, str):
            try:
                target = TaskStatus(target)
            except ValueError:
                return ""
        return cls._TRANSITIONS.get((current, target), "")
