"""
Phase 10 单元测试：恢复协调器（RecoveryCoordinator）。

做什么：全面测试 RecoveryCoordinator 的任务恢复、Gating 审批恢复和情绪冻结恢复。
为什么这样做：确保中断恢复逻辑正确处理各种中断类型和边界条件。
覆盖范围：
    - recover_task: 正常恢复、无快照、格式异常
    - resume_after_gating: 正常恢复、非挂起状态
    - resume_after_freeze: 正常恢复、无冻结快照
"""

import json
import pytest

from app.state.recovery import RecoveryCoordinator, RecoveryResult
from app.state.task_state_machine import TaskStatus


# ===========================================================================
# Mock 快照管理器
# ===========================================================================


class MockSnapshotManager:
    """模拟 SnapshotManager，可以配置返回不同的快照数据。"""

    def __init__(self):
        self._snapshots = {}
        self._freeze_data = {}

    def set_snapshot(self, task_id: str, data: dict):
        """设置模拟快照数据。"""
        self._snapshots[task_id] = data

    async def load_latest_snapshot(self, task_id: str) -> dict | None:
        return self._snapshots.get(task_id)

    async def save_freeze_snapshot(self, task_id: str, dag_state: dict, esm_before: str) -> bool:
        self._freeze_data[task_id] = {"dag_state_json": dag_state, "esm_before": esm_before}
        return True

    async def load_freeze_snapshot(self, task_id: str) -> dict | None:
        return self._freeze_data.get(task_id)

    async def delete_freeze_snapshot(self, task_id: str) -> bool:
        self._freeze_data.pop(task_id, None)
        return True


class TestRecoveryCoordinator:
    """RecoveryCoordinator 基础测试。"""

    @pytest.mark.asyncio
    async def test_init_without_deps(self):
        """验证无依赖时初始化成功。"""
        coordinator = RecoveryCoordinator()
        assert coordinator is not None

    @pytest.mark.asyncio
    async def test_recover_task_success(self):
        """验证正常恢复任务。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr.set_snapshot("task-ok", {
            "plan": {
                "plan_id": "plan-1",
                "session_id": "session-1",
                "trace_id": "trace-1",
                "states": [
                    {"state_id": "s1", "order_index": 0},
                    {"state_id": "s2", "order_index": 1},
                ],
            },
            "cursor": 1,
            "terminated": True,
            "state_runtimes": {
                "s1": {"status": "SUCCEEDED"},
                "s2": {"status": "RUNNING"},
            },
            "executor_runtime": {
                "state_runtime": {"status": "RUNNING", "steps_completed": 2},
            },
            "budget_consumed": {"tool_calls": 5},
            "gating_suspended": False,
            "gating_pending_node_ids": [],
        })

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-ok")

        assert result.success is True
        assert result.task_status == TaskStatus.RECOVERING
        assert result.recovered_cursor == 1
        assert result.dag_state is not None

        # 验证 RUNNING 状态的 State 被重置为 PENDING
        assert result.dag_state["state_runtimes"]["s2"]["status"] == "PENDING"

        # 验证 terminated 被清除
        assert result.dag_state["terminated"] is False
        assert result.dag_state["termination_reason"] == ""

        # 验证 executor_runtime 中的 RUNNING 被重置
        rt = result.dag_state["executor_runtime"]["state_runtime"]
        assert rt["status"] == "PENDING"
        assert rt["steps_completed"] == 0

    @pytest.mark.asyncio
    async def test_recover_task_no_snapshot(self):
        """验证无快照时恢复失败。"""
        snap_mgr = MockSnapshotManager()
        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-nonexistent")

        assert result.success is False
        assert "无可用快照" in result.reason
        assert result.task_status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_recover_task_json_string(self):
        """验证从 JSON 字符串恢复。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr.set_snapshot("task-json", json.dumps({
            "plan": {"plan_id": "p1", "states": []},
            "cursor": 0,
            "terminated": False,
            "state_runtimes": {},
            "executor_runtime": {},
            "budget_consumed": {"tool_calls": 0},
            "gating_suspended": False,
            "gating_pending_node_ids": [],
        }))

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-json")
        assert result.success is True
        assert result.dag_state["plan"]["plan_id"] == "p1"

    @pytest.mark.asyncio
    async def test_recover_task_invalid_json(self):
        """验证无效 JSON 字符串恢复失败。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr.set_snapshot("task-bad-json", "这不是 JSON{{{")

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-bad-json")
        assert result.success is False
        assert "JSON" in result.reason

    @pytest.mark.asyncio
    async def test_recover_task_invalid_type(self):
        """验证非 dict 非 str 格式的恢复失败。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr.set_snapshot("task-bad-type", 12345)

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-bad-type")
        assert result.success is False
        assert "格式异常" in result.reason

    @pytest.mark.asyncio
    async def test_recover_no_dag_state(self):
        """验证 dag_state 为 None 时恢复失败。"""
        coordinator = RecoveryCoordinator(snapshot_manager=None)
        result = await coordinator.recover_task("task-null")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_recover_with_gating_suspended_warning(self):
        """验证恢复时检测到 Gating 挂起状态（不阻断恢复）。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr.set_snapshot("task-gating", {
            "plan": {"plan_id": "p1", "states": []},
            "cursor": 0,
            "terminated": True,
            "state_runtimes": {},
            "executor_runtime": {},
            "budget_consumed": {"tool_calls": 0},
            "gating_suspended": True,
            "gating_pending_node_ids": ["node-1"],
        })

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.recover_task("task-gating")
        assert result.success is True
        # Gating 挂起标志不应被清除（恢复时只记录警告）
        assert result.dag_state["gating_suspended"] is True


class TestResumeAfterGating:
    """Gating 审批恢复测试。"""

    @pytest.mark.asyncio
    async def test_resume_after_gating_success(self):
        """验证 Gating 审批后成功恢复。"""
        coordinator = RecoveryCoordinator()
        dag_state = {
            "cursor": 2,
            "gating_suspended": True,
            "gating_pending_node_ids": ["node-l2-tool"],
            "executor_runtime": {
                "step_context": {},
            },
        }

        approval_result = {
            "audit_log_id": "audit-123",
            "approved": True,
            "user_feedback": "同意执行",
        }

        result = await coordinator.resume_after_gating(
            task_id="task-gating-resume",
            dag_state=dag_state,
            approval_result=approval_result,
        )

        assert result.success is True
        assert result.task_status == TaskStatus.RUNNING
        assert result.dag_state["gating_suspended"] is False
        assert result.dag_state["executor_runtime"]["step_context"]["gating_approval_result"]["approved"] is True

    @pytest.mark.asyncio
    async def test_resume_after_gating_not_suspended(self):
        """验证非挂起状态拒绝恢复。"""
        coordinator = RecoveryCoordinator()
        dag_state = {
            "cursor": 1,
            "gating_suspended": False,
            "gating_pending_node_ids": [],
            "executor_runtime": {},
        }

        result = await coordinator.resume_after_gating(
            task_id="task-not-suspended",
            dag_state=dag_state,
            approval_result={"approved": True},
        )

        assert result.success is False
        assert "未处于 Gating 挂起状态" in result.reason


class TestResumeAfterFreeze:
    """情绪冻结恢复测试。"""

    @pytest.mark.asyncio
    async def test_resume_after_freeze_success(self):
        """验证情绪冻结后成功恢复。"""
        snap_mgr = MockSnapshotManager()
        await snap_mgr.save_freeze_snapshot(
            task_id="task-freeze-ok",
            dag_state={"cursor": 3, "terminated": True},
            esm_before="ANGRY",
        )

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.resume_after_freeze("task-freeze-ok")

        assert result.success is True
        assert result.task_status == TaskStatus.RUNNING
        assert result.dag_state is not None
        assert result.dag_state["cursor"] == 3
        assert result.dag_state["terminated"] is False
        assert "ANGRY" in result.reason

    @pytest.mark.asyncio
    async def test_resume_after_freeze_no_snapshot(self):
        """验证无冻结快照时恢复失败。"""
        snap_mgr = MockSnapshotManager()
        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.resume_after_freeze("task-no-freeze")

        assert result.success is False
        assert "无情绪冻结快照" in result.reason

    @pytest.mark.asyncio
    async def test_resume_after_freeze_no_snap_mgr(self):
        """验证无 SnapshotManager 时恢复失败。"""
        coordinator = RecoveryCoordinator()
        result = await coordinator.resume_after_freeze("task-no-mgr")

        assert result.success is False
        assert "SnapshotManager 未初始化" in result.reason

    @pytest.mark.asyncio
    async def test_resume_after_freeze_json_string(self):
        """验证快照 dag_state_json 为字符串时的恢复。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr._freeze_data["task-freeze-json"] = {
            "dag_state_json": json.dumps({"cursor": 5, "terminated": True}),
            "esm_before": "NEUTRAL",
        }

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.resume_after_freeze("task-freeze-json")

        assert result.success is True
        assert result.dag_state["cursor"] == 5

    @pytest.mark.asyncio
    async def test_resume_after_freeze_invalid_json(self):
        """验证无效 JSON 字符串恢复失败。"""
        snap_mgr = MockSnapshotManager()
        snap_mgr._freeze_data["task-freeze-bad"] = {
            "dag_state_json": "{{{NOT JSON}}}",
            "esm_before": "NEUTRAL",
        }

        coordinator = RecoveryCoordinator(snapshot_manager=snap_mgr)
        result = await coordinator.resume_after_freeze("task-freeze-bad")

        assert result.success is False
        assert "JSON" in result.reason


class TestRecoveryResult:
    """RecoveryResult 数据模型测试。"""

    def test_default_failure(self):
        """验证默认 RecoveryResult 为失败状态。"""
        result = RecoveryResult()
        assert result.success is False
        assert result.dag_state is None
        assert result.task_status == TaskStatus.FAILED

    def test_success_result(self):
        """验证构造成功结果。"""
        result = RecoveryResult(
            success=True,
            dag_state={"cursor": 5},
            task_status=TaskStatus.RECOVERING,
            reason="恢复成功",
            recovered_cursor=5,
            recovered_snapshot_version=2,
        )
        assert result.success is True
        assert result.dag_state["cursor"] == 5
        assert result.task_status == TaskStatus.RECOVERING
        assert result.recovered_cursor == 5
        assert result.recovered_snapshot_version == 2
