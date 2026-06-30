"""
Luna AI 任务状态管理模块。

做什么：提供任务级状态机（TaskStatus）、状态跃迁管理、快照持久化与中断恢复协调。
为什么这样做：Phase 10 要求实现任务级别的生命周期管理，与 DAG 节点级状态（DagNodeStatus）分离，
             形成 Plan 级与节点级的双层状态管理体系。
"""

from app.state.task_state_machine import TaskStatus, TaskStateMachine
from app.state.state_transition import StateTransitionManager, StateTransitionLog
from app.state.snapshot_manager import SnapshotManager
from app.state.recovery import RecoveryCoordinator, RecoveryResult

__all__ = [
    "TaskStatus",
    "TaskStateMachine",
    "StateTransitionManager",
    "StateTransitionLog",
    "SnapshotManager",
    "RecoveryCoordinator",
    "RecoveryResult",
]