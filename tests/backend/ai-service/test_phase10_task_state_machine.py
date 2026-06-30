"""
Phase 10 单元测试：任务状态机（TaskStatus + TaskStateMachine）。

做什么：全面测试 TaskStatus 枚举值、TaskStateMachine 状态跃迁合法性校验、终态判断、
        可查询合法跃迁目标、触发原因查询等功能。
为什么这样做：确保状态机跃迁规则表正确覆盖所有场景，防止非法跃迁导致状态不一致。
覆盖范围：
    - 正常流程：所有合法跃迁路径
    - 异常分支：非法跃迁、未知状态、终态禁跃迁
    - 边界条件：自同状态跃迁、空输入、字符串输入
"""

import pytest

from app.state.task_state_machine import TaskStatus, TaskStateMachine


class TestTaskStatus:
    """TaskStatus 枚举值测试。"""

    def test_created_exists(self):
        """验证 CREATED 状态存在且值正确。"""
        assert TaskStatus.CREATED.value == "CREATED"

    def test_running_exists(self):
        """验证 RUNNING 状态存在且值正确。"""
        assert TaskStatus.RUNNING.value == "RUNNING"

    def test_paused_exists(self):
        """验证 PAUSED 状态存在且值正确。"""
        assert TaskStatus.PAUSED.value == "PAUSED"

    def test_succeeded_exists(self):
        """验证 SUCCEEDED 状态存在且值正确。"""
        assert TaskStatus.SUCCEEDED.value == "SUCCEEDED"

    def test_failed_exists(self):
        """验证 FAILED 状态存在且值正确。"""
        assert TaskStatus.FAILED.value == "FAILED"

    def test_terminated_exists(self):
        """验证 TERMINATED 状态存在且值正确。"""
        assert TaskStatus.TERMINATED.value == "TERMINATED"

    def test_timed_out_exists(self):
        """验证 TIMED_OUT 状态存在且值正确。"""
        assert TaskStatus.TIMED_OUT.value == "TIMED_OUT"

    def test_budget_exhausted_exists(self):
        """验证 BUDGET_EXHAUSTED 状态存在且值正确。"""
        assert TaskStatus.BUDGET_EXHAUSTED.value == "BUDGET_EXHAUSTED"

    def test_recovering_exists(self):
        """验证 RECOVERING 状态存在且值正确。"""
        assert TaskStatus.RECOVERING.value == "RECOVERING"

    def test_snapshot_restored_exists(self):
        """验证 SNAPSHOT_RESTORED 状态存在且值正确。"""
        assert TaskStatus.SNAPSHOT_RESTORED.value == "SNAPSHOT_RESTORED"

    def test_all_statuses_are_string_enum(self):
        """验证所有状态都是字符串枚举类型。"""
        for status in TaskStatus:
            assert isinstance(status.value, str)

    def test_enum_from_string(self):
        """验证从字符串构造枚举。"""
        assert TaskStatus("CREATED") == TaskStatus.CREATED
        assert TaskStatus("RUNNING") == TaskStatus.RUNNING

    def test_enum_from_invalid_string_raises(self):
        """验证无效字符串抛出 ValueError。"""
        with pytest.raises(ValueError):
            TaskStatus("INVALID_STATUS")


class TestTaskStateMachineCanTransition:
    """TaskStateMachine.can_transition() 测试。"""

    def test_created_to_planning_is_valid(self):
        """CREATED -> PLANNING 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.CREATED, TaskStatus.PLANNING) is True

    def test_created_to_terminated_is_valid(self):
        """CREATED -> TERMINATED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.CREATED, TaskStatus.TERMINATED) is True

    def test_planning_to_plan_ready_is_valid(self):
        """PLANNING -> PLAN_READY 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY) is True

    def test_plan_ready_to_running_is_valid(self):
        """PLAN_READY -> RUNNING 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING) is True

    def test_running_to_paused_is_valid(self):
        """RUNNING -> PAUSED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.PAUSED) is True

    def test_running_to_succeeded_is_valid(self):
        """RUNNING -> SUCCEEDED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED) is True

    def test_running_to_failed_is_valid(self):
        """RUNNING -> FAILED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.FAILED) is True

    def test_running_to_timed_out_is_valid(self):
        """RUNNING -> TIMED_OUT 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.TIMED_OUT) is True

    def test_running_to_budget_exhausted_is_valid(self):
        """RUNNING -> BUDGET_EXHAUSTED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.BUDGET_EXHAUSTED) is True

    def test_running_to_degraded_is_valid(self):
        """RUNNING -> DEGRADED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.DEGRADED) is True

    def test_running_to_pending_approval_is_valid(self):
        """RUNNING -> PENDING_APPROVAL 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.PENDING_APPROVAL) is True

    def test_running_to_gating_suspended_is_valid(self):
        """RUNNING -> GATING_SUSPENDED 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.RUNNING, TaskStatus.GATING_SUSPENDED) is True

    def test_paused_to_running_is_valid(self):
        """PAUSED -> RUNNING 是合法跃迁（恢复）。"""
        assert TaskStateMachine.can_transition(TaskStatus.PAUSED, TaskStatus.RUNNING) is True

    def test_pending_approval_to_running_is_valid(self):
        """PENDING_APPROVAL -> RUNNING 是合法跃迁（用户同意）。"""
        assert TaskStateMachine.can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.RUNNING) is True

    def test_pending_approval_to_failed_is_valid(self):
        """PENDING_APPROVAL -> FAILED 是合法跃迁（用户拒绝）。"""
        assert TaskStateMachine.can_transition(TaskStatus.PENDING_APPROVAL, TaskStatus.FAILED) is True

    def test_gating_suspended_to_running_is_valid(self):
        """GATING_SUSPENDED -> RUNNING 是合法跃迁（审批完成）。"""
        assert TaskStateMachine.can_transition(TaskStatus.GATING_SUSPENDED, TaskStatus.RUNNING) is True

    def test_degraded_to_running_is_valid(self):
        """DEGRADED -> RUNNING 是合法跃迁（重规划完成）。"""
        assert TaskStateMachine.can_transition(TaskStatus.DEGRADED, TaskStatus.RUNNING) is True

    def test_recovering_to_running_is_valid(self):
        """RECOVERING -> RUNNING 是合法跃迁（恢复完成）。"""
        assert TaskStateMachine.can_transition(TaskStatus.RECOVERING, TaskStatus.RUNNING) is True

    def test_recovering_to_failed_is_valid(self):
        """RECOVERING -> FAILED 是合法跃迁（恢复失败）。"""
        assert TaskStateMachine.can_transition(TaskStatus.RECOVERING, TaskStatus.FAILED) is True

    def test_snapshot_restored_to_running_is_valid(self):
        """SNAPSHOT_RESTORED -> RUNNING 是合法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.SNAPSHOT_RESTORED, TaskStatus.RUNNING) is True


class TestTaskStateMachineCanTransitionIllegal:
    """非法跃迁测试。"""

    def test_succeeded_cannot_transition(self):
        """终态 SUCCEEDED 禁止跃迁到任何状态。"""
        assert TaskStateMachine.can_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING) is False
        assert TaskStateMachine.can_transition(TaskStatus.SUCCEEDED, TaskStatus.FAILED) is False

    def test_failed_cannot_transition(self):
        """终态 FAILED 禁止跃迁到任何状态。"""
        assert TaskStateMachine.can_transition(TaskStatus.FAILED, TaskStatus.RUNNING) is False

    def test_terminated_cannot_transition(self):
        """终态 TERMINATED 禁止跃迁到任何状态。"""
        assert TaskStateMachine.can_transition(TaskStatus.TERMINATED, TaskStatus.CREATED) is False

    def test_timed_out_cannot_transition(self):
        """终态 TIMED_OUT 禁止跃迁到任何状态。"""
        assert TaskStateMachine.can_transition(TaskStatus.TIMED_OUT, TaskStatus.RUNNING) is False

    def test_budget_exhausted_cannot_transition(self):
        """终态 BUDGET_EXHAUSTED 禁止跃迁到任何状态。"""
        assert TaskStateMachine.can_transition(TaskStatus.BUDGET_EXHAUSTED, TaskStatus.RUNNING) is False

    def test_created_cannot_go_to_running(self):
        """CREATED -> RUNNING 是非法跃迁（必须先经过 PLANNING）。"""
        assert TaskStateMachine.can_transition(TaskStatus.CREATED, TaskStatus.RUNNING) is False

    def test_created_cannot_go_to_succeeded(self):
        """CREATED -> SUCCEEDED 是非法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.CREATED, TaskStatus.SUCCEEDED) is False

    def test_planning_cannot_go_to_running(self):
        """PLANNING -> RUNNING 是非法跃迁（必须先经过 PLAN_READY）。"""
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.RUNNING) is False

    def test_paused_cannot_go_to_succeeded(self):
        """PAUSED -> SUCCEEDED 是非法跃迁。"""
        assert TaskStateMachine.can_transition(TaskStatus.PAUSED, TaskStatus.SUCCEEDED) is False


class TestTaskStateMachineCanTransitionString:
    """字符串输入测试。"""

    def test_string_input_valid(self):
        """验证字符串输入的合法跃迁。"""
        assert TaskStateMachine.can_transition("CREATED", "PLANNING") is True

    def test_string_input_invalid_from(self):
        """验证无效的 from 状态字符串返回 False。"""
        assert TaskStateMachine.can_transition("INVALID", "RUNNING") is False

    def test_string_input_invalid_to(self):
        """验证无效的 to 状态字符串返回 False。"""
        assert TaskStateMachine.can_transition("CREATED", "INVALID") is False


class TestTaskStateMachineTransition:
    """TaskStateMachine.transition() 测试。"""

    def test_valid_transition_returns_success(self):
        """合法跃迁返回 (True, trigger_reason)。"""
        success, reason = TaskStateMachine.transition(
            TaskStatus.CREATED, TaskStatus.PLANNING
        )
        assert success is True
        assert "规划" in reason

    def test_same_status_returns_success(self):
        """自同状态跃迁返回 (True, '状态未变更')。"""
        success, reason = TaskStateMachine.transition(
            TaskStatus.RUNNING, TaskStatus.RUNNING
        )
        assert success is True
        assert "未变更" in reason

    def test_invalid_transition_returns_failure(self):
        """非法跃迁返回 (False, reason)。"""
        success, reason = TaskStateMachine.transition(
            TaskStatus.SUCCEEDED, TaskStatus.RUNNING
        )
        assert success is False
        assert "非法" in reason

    def test_invalid_from_status_returns_failure(self):
        """无效的 from 状态字符串返回 (False, reason)。"""
        success, reason = TaskStateMachine.transition(
            "INVALID_STATUS", TaskStatus.RUNNING
        )
        assert success is False
        assert "未知" in reason

    def test_invalid_to_status_returns_failure(self):
        """无效的 to 状态字符串返回 (False, reason)。"""
        success, reason = TaskStateMachine.transition(
            TaskStatus.CREATED, "INVALID_STATUS"
        )
        assert success is False
        assert "未知" in reason

    def test_transition_with_trace_and_task_ids(self):
        """验证跃迁时传入 trace_id 和 task_id 不影响结果。"""
        success, reason = TaskStateMachine.transition(
            TaskStatus.RUNNING, TaskStatus.SUCCEEDED,
            trace_id="test-trace-123",
            task_id="test-task-456",
        )
        assert success is True


class TestTaskStateMachineIsTerminal:
    """TaskStateMachine.is_terminal() 测试。"""

    def test_succeeded_is_terminal(self):
        """SUCCEEDED 是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.SUCCEEDED) is True

    def test_failed_is_terminal(self):
        """FAILED 是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.FAILED) is True

    def test_terminated_is_terminal(self):
        """TERMINATED 是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.TERMINATED) is True

    def test_timed_out_is_terminal(self):
        """TIMED_OUT 是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.TIMED_OUT) is True

    def test_budget_exhausted_is_terminal(self):
        """BUDGET_EXHAUSTED 是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.BUDGET_EXHAUSTED) is True

    def test_running_is_not_terminal(self):
        """RUNNING 不是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.RUNNING) is False

    def test_created_is_not_terminal(self):
        """CREATED 不是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.CREATED) is False

    def test_paused_is_not_terminal(self):
        """PAUSED 不是终态。"""
        assert TaskStateMachine.is_terminal(TaskStatus.PAUSED) is False

    def test_string_input_is_terminal(self):
        """验证字符串输入的终态判断。"""
        assert TaskStateMachine.is_terminal("SUCCEEDED") is True
        assert TaskStateMachine.is_terminal("RUNNING") is False

    def test_invalid_string_is_not_terminal(self):
        """无效字符串返回 False。"""
        assert TaskStateMachine.is_terminal("INVALID") is False


class TestTaskStateMachineGetNextAllowedStates:
    """TaskStateMachine.get_next_allowed_states() 测试。"""

    def test_created_allows_planning_and_terminated(self):
        """CREATED 状态允许跃迁到 PLANNING 和 TERMINATED。"""
        allowed = TaskStateMachine.get_next_allowed_states(TaskStatus.CREATED)
        assert TaskStatus.PLANNING in allowed
        assert TaskStatus.TERMINATED in allowed
        assert len(allowed) == 2

    def test_running_allows_many_targets(self):
        """RUNNING 状态允许跃迁到多个目标状态。"""
        allowed = TaskStateMachine.get_next_allowed_states(TaskStatus.RUNNING)
        assert TaskStatus.PAUSED in allowed
        assert TaskStatus.SUCCEEDED in allowed
        assert TaskStatus.FAILED in allowed
        assert TaskStatus.TIMED_OUT in allowed
        assert TaskStatus.BUDGET_EXHAUSTED in allowed
        assert TaskStatus.DEGRADED in allowed
        assert TaskStatus.PENDING_APPROVAL in allowed
        assert TaskStatus.GATING_SUSPENDED in allowed
        assert TaskStatus.TERMINATED in allowed
        assert len(allowed) >= 9

    def test_terminal_returns_empty(self):
        """终态返回空列表。"""
        assert TaskStateMachine.get_next_allowed_states(TaskStatus.SUCCEEDED) == []
        assert TaskStateMachine.get_next_allowed_states(TaskStatus.FAILED) == []
        assert TaskStateMachine.get_next_allowed_states(TaskStatus.TERMINATED) == []
        assert TaskStateMachine.get_next_allowed_states(TaskStatus.TIMED_OUT) == []
        assert TaskStateMachine.get_next_allowed_states(TaskStatus.BUDGET_EXHAUSTED) == []

    def test_paused_allows_running_and_terminated(self):
        """PAUSED 状态允许跃迁到 RUNNING 和 TERMINATED。"""
        allowed = TaskStateMachine.get_next_allowed_states(TaskStatus.PAUSED)
        assert TaskStatus.RUNNING in allowed
        assert TaskStatus.TERMINATED in allowed

    def test_invalid_string_returns_empty(self):
        """无效字符串返回空列表。"""
        assert TaskStateMachine.get_next_allowed_states("INVALID") == []


class TestTaskStateMachineGetTriggerReason:
    """TaskStateMachine.get_trigger_reason() 测试。"""

    def test_created_to_planning_reason(self):
        """CREATED -> PLANNING 的触发原因。"""
        reason = TaskStateMachine.get_trigger_reason(TaskStatus.CREATED, TaskStatus.PLANNING)
        assert "规划" in reason

    def test_running_to_paused_reason(self):
        """RUNNING -> PAUSED 的触发原因包含暂停/冻结描述。"""
        reason = TaskStateMachine.get_trigger_reason(TaskStatus.RUNNING, TaskStatus.PAUSED)
        assert "暂停" in reason or "冻结" in reason

    def test_running_to_succeeded_reason(self):
        """RUNNING -> SUCCEEDED 的触发原因。"""
        reason = TaskStateMachine.get_trigger_reason(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
        assert "成功" in reason or "完成" in reason

    def test_invalid_transition_returns_empty(self):
        """非法跃迁返回空字符串。"""
        reason = TaskStateMachine.get_trigger_reason(TaskStatus.SUCCEEDED, TaskStatus.RUNNING)
        assert reason == ""

    def test_recovering_to_running_reason(self):
        """RECOVERING -> RUNNING 的触发原因。"""
        reason = TaskStateMachine.get_trigger_reason(TaskStatus.RECOVERING, TaskStatus.RUNNING)
        assert "恢复" in reason


class TestTaskStateMachineFullLifecycle:
    """完整生命周期测试 — 模拟任务从创建到完成的全部跃迁路径。"""

    def test_full_success_lifecycle(self):
        """测试任务从 CREATED 到 SUCCEEDED 的完整生命周期。"""
        # 1. CREATED -> PLANNING
        success, _ = TaskStateMachine.transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        assert success

        # 2. PLANNING -> PLAN_READY
        success, _ = TaskStateMachine.transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY)
        assert success

        # 3. PLAN_READY -> RUNNING
        success, _ = TaskStateMachine.transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING)
        assert success

        # 4. RUNNING -> SUCCEEDED
        success, _ = TaskStateMachine.transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
        assert success

    def test_full_pause_resume_lifecycle(self):
        """测试任务暂停和恢复的完整生命周期。"""
        # 先到达 RUNNING
        TaskStateMachine.transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        TaskStateMachine.transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY)
        TaskStateMachine.transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING)

        # RUNNING -> PAUSED
        success, _ = TaskStateMachine.transition(TaskStatus.RUNNING, TaskStatus.PAUSED)
        assert success

        # PAUSED -> RUNNING
        success, _ = TaskStateMachine.transition(TaskStatus.PAUSED, TaskStatus.RUNNING)
        assert success

    def test_full_gating_lifecycle(self):
        """测试 Gating 审批挂起和恢复的完整生命周期。"""
        # 先到达 RUNNING
        TaskStateMachine.transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        TaskStateMachine.transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY)
        TaskStateMachine.transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING)

        # RUNNING -> GATING_SUSPENDED
        success, _ = TaskStateMachine.transition(TaskStatus.RUNNING, TaskStatus.GATING_SUSPENDED)
        assert success

        # GATING_SUSPENDED -> RUNNING
        success, _ = TaskStateMachine.transition(TaskStatus.GATING_SUSPENDED, TaskStatus.RUNNING)
        assert success

    def test_full_degraded_lifecycle(self):
        """测试降级和恢复的完整生命周期。"""
        # 先到达 RUNNING
        TaskStateMachine.transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        TaskStateMachine.transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY)
        TaskStateMachine.transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING)

        # RUNNING -> DEGRADED
        success, _ = TaskStateMachine.transition(TaskStatus.RUNNING, TaskStatus.DEGRADED)
        assert success

        # DEGRADED -> RUNNING
        success, _ = TaskStateMachine.transition(TaskStatus.DEGRADED, TaskStatus.RUNNING)
        assert success

    def test_full_recovery_lifecycle(self):
        """测试崩溃恢复的完整生命周期。"""
        # 直接进入 RECOVERING（从快照恢复）
        success, _ = TaskStateMachine.transition(TaskStatus.RECOVERING, TaskStatus.RUNNING)
        assert success

    def test_full_timeout_lifecycle(self):
        """测试超时终止的完整生命周期。"""
        # 先到达 RUNNING
        TaskStateMachine.transition(TaskStatus.CREATED, TaskStatus.PLANNING)
        TaskStateMachine.transition(TaskStatus.PLANNING, TaskStatus.PLAN_READY)
        TaskStateMachine.transition(TaskStatus.PLAN_READY, TaskStatus.RUNNING)

        # RUNNING -> TIMED_OUT
        success, _ = TaskStateMachine.transition(TaskStatus.RUNNING, TaskStatus.TIMED_OUT)
        assert success

        # TIMED_OUT 是终态，不能继续
        assert TaskStateMachine.is_terminal(TaskStatus.TIMED_OUT)
        success, _ = TaskStateMachine.transition(TaskStatus.TIMED_OUT, TaskStatus.RUNNING)
        assert success is False
