"""
Phase 10 单元测试：状态跃迁管理（StateTransitionManager + StateTransitionLog）。

做什么：全面测试 StateTransitionLog 的构建、StateTransitionManager 的日志写入和查询。
为什么这样做：确保跃迁审计日志的格式一致性，验证持久化逻辑的降级行为。
覆盖范围：
    - StateTransitionLog 构造与序列化
    - StateTransitionManager 日志写入（含降级）
    - 触发类型常量完整性
"""

import pytest
from datetime import datetime

from app.state.task_state_machine import TaskStatus
from app.state.state_transition import StateTransitionLog, StateTransitionManager


class TestStateTransitionLog:
    """StateTransitionLog 测试。"""

    def test_log_creation_with_enums(self):
        """验证使用 TaskStatus 枚举构造日志。"""
        log = StateTransitionLog(
            session_id="test-session",
            prev_status=TaskStatus.RUNNING,
            next_status=TaskStatus.SUCCEEDED,
            trigger_type=StateTransitionLog.TRIGGER_NORMAL,
            transition_reason="全部 State 完成",
            task_id="test-task",
            trace_id="test-trace",
        )
        assert log.session_id == "test-session"
        assert log.prev_wsm == "RUNNING"
        assert log.next_wsm == "SUCCEEDED"
        assert log.trigger_type == "NORMAL_ADVANCE"
        assert log.task_id == "test-task"
        assert log.trace_id == "test-trace"

    def test_log_creation_with_strings(self):
        """验证使用字符串构造日志。"""
        log = StateTransitionLog(
            session_id="test-session",
            prev_status="RUNNING",
            next_status="PAUSED",
            trigger_type=StateTransitionLog.TRIGGER_EMOTION,
            transition_reason="情绪冻结",
        )
        assert log.prev_wsm == "RUNNING"
        assert log.next_wsm == "PAUSED"
        assert log.trigger_type == "EMOTION_INTERRUPT"

    def test_log_creation_with_esm(self):
        """验证 ESM 情绪状态字段。"""
        log = StateTransitionLog(
            session_id="test-session",
            prev_status="RUNNING",
            next_status="PAUSED",
            prev_esm="NEUTRAL",
            next_esm="ANGRY",
        )
        assert log.prev_esm == "NEUTRAL"
        assert log.next_esm == "ANGRY"

    def test_log_with_auto_generated_id(self):
        """验证日志自动生成雪花 ID。"""
        log = StateTransitionLog(
            session_id="test-session",
            prev_status="CREATED",
            next_status="PLANNING",
        )
        assert log.log_id is not None
        assert len(log.log_id) > 0

    def test_log_to_dict(self):
        """验证 to_dict() 输出格式。"""
        log = StateTransitionLog(
            session_id="test-session",
            prev_status="RUNNING",
            next_status="SUCCEEDED",
            trigger_type=StateTransitionLog.TRIGGER_NORMAL,
            transition_reason="完成",
            task_id="task-1",
            trace_id="trace-1",
        )
        data = log.to_dict()
        assert data["session_id"] == "test-session"
        assert data["prev_wsm"] == "RUNNING"
        assert data["next_wsm"] == "SUCCEEDED"
        assert data["trigger_type"] == "NORMAL_ADVANCE"
        assert data["task_id"] == "task-1"
        assert data["trace_id"] == "trace-1"
        assert data["id"] == log.log_id
        assert isinstance(data["created_at"], datetime)

    def test_all_trigger_types_present(self):
        """验证所有触发类型常量都定义。"""
        assert StateTransitionLog.TRIGGER_NORMAL == "NORMAL_ADVANCE"
        assert StateTransitionLog.TRIGGER_EMOTION == "EMOTION_INTERRUPT"
        assert StateTransitionLog.TRIGGER_RESUME == "RESUME"
        assert StateTransitionLog.TRIGGER_FALLBACK == "FALLBACK"
        assert StateTransitionLog.TRIGGER_TIMEOUT == "TIMEOUT"
        assert StateTransitionLog.TRIGGER_USER_CANCEL == "USER_CANCEL"
        assert StateTransitionLog.TRIGGER_GATING == "GATING"
        assert StateTransitionLog.TRIGGER_BUDGET == "BUDGET_EXHAUSTED"
        assert StateTransitionLog.TRIGGER_RECOVERY == "RECOVERY"
        assert StateTransitionLog.TRIGGER_CRASH == "CRASH"


class TestStateTransitionManager:
    """StateTransitionManager 测试。"""

    @pytest.mark.asyncio
    async def test_log_transaction_without_pg(self):
        """验证无 PG 连接时日志降级（记录但返回 ID）。"""
        manager = StateTransitionManager(pg_pool=None)

        log_id = await manager.log_transition(
            session_id="test-session",
            prev_status=TaskStatus.RUNNING,
            next_status=TaskStatus.SUCCEEDED,
            trigger_type=StateTransitionLog.TRIGGER_NORMAL,
        )
        # 即使没有 PG，也应返回日志 ID
        assert log_id is not None
        assert len(log_id) > 0

    @pytest.mark.asyncio
    async def test_query_logs_without_pg(self):
        """验证无 PG 连接时查询返回空列表。"""
        manager = StateTransitionManager(pg_pool=None)
        logs = await manager.query_logs(session_id="test-session")
        assert logs == []

    @pytest.mark.asyncio
    async def test_delete_logs_without_pg(self):
        """验证无 PG 连接时删除返回 False。"""
        manager = StateTransitionManager(pg_pool=None)
        result = await manager.delete_logs_by_session("test-session")
        assert result is False

    @pytest.mark.asyncio
    async def test_log_transaction_with_various_triggers(self):
        """验证各种触发类型的日志记录。"""
        manager = StateTransitionManager(pg_pool=None)

        # 测试各种触发类型
        triggers = [
            ("RUNNING", "PAUSED", StateTransitionLog.TRIGGER_EMOTION),
            ("PAUSED", "RUNNING", StateTransitionLog.TRIGGER_RESUME),
            ("RUNNING", "TIMED_OUT", StateTransitionLog.TRIGGER_TIMEOUT),
            ("RUNNING", "TERMINATED", StateTransitionLog.TRIGGER_USER_CANCEL),
            ("RUNNING", "GATING_SUSPENDED", StateTransitionLog.TRIGGER_GATING),
            ("RUNNING", "BUDGET_EXHAUSTED", StateTransitionLog.TRIGGER_BUDGET),
            ("RECOVERING", "RUNNING", StateTransitionLog.TRIGGER_RECOVERY),
        ]

        for prev, next_, trigger in triggers:
            log_id = await manager.log_transition(
                session_id="test-session",
                prev_status=prev,
                next_status=next_,
                trigger_type=trigger,
            )
            assert log_id is not None

    @pytest.mark.asyncio
    async def test_log_with_full_esm_context(self):
        """验证包含 ESM 情绪状态的日志记录。"""
        manager = StateTransitionManager(pg_pool=None)

        from app.state.task_state_machine import TaskStatus

        log_id = await manager.log_transition(
            session_id="test-session",
            prev_status=TaskStatus.RUNNING,
            next_status=TaskStatus.PAUSED,
            trigger_type=StateTransitionLog.TRIGGER_EMOTION,
            transition_reason="检测到高危情绪 ANGRY，冻结任务",
            trace_id="trace-esm-123",
            task_id="task-esm-456",
            turn_id="turn-789",
            prev_esm="NEUTRAL",
            next_esm="ANGRY",
        )
        assert log_id is not None
