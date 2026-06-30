"""
Phase 10 单元测试：快照管理器（SnapshotManager）。

做什么：全面测试快照的保存、加载、列表查询、删除以及情绪冻结快照功能。
为什么这样做：确保 SnapshotManager 在 Redis/PG 可用与不可用时的正确降级行为。
覆盖范围：
    - save_snapshot / load_latest_snapshot
    - list_snapshots / load_snapshot_by_version
    - delete_snapshot
    - save_freeze_snapshot / load_freeze_snapshot / delete_freeze_snapshot
    - 无 Redis/PG 时的降级行为
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.state.snapshot_manager import SnapshotManager


# ===========================================================================
# Mock 辅助类
# ===========================================================================


class MockRedisClient:
    """模拟 Redis 客户端。"""
    def __init__(self):
        self._data = {}

    def get_client(self):
        return self

    async def get(self, key):
        return self._data.get(key)

    async def setex(self, key, ttl, value):
        self._data[key] = value

    async def delete(self, key):
        self._data.pop(key, None)
        return 1

    async def scan(self, cursor=0, match="*", count=100):
        """模拟 SCAN 命令。"""
        import fnmatch
        all_keys = list(self._data.keys())
        matched = [k for k in all_keys if fnmatch.fnmatch(k, match)]
        return (0, matched)


class MockPGPool:
    """模拟 PostgreSQL 连接池。"""
    def __init__(self):
        self._rows = []
        self._next_version = {}

    async def execute(self, query, *params):
        """模拟 execute。"""
        pass

    async def fetchrow(self, query, *params):
        """模拟 fetchrow 返回单行。"""
        if self._rows:
            row = self._rows[-1]
            return row
        return None

    async def fetch(self, query, *params):
        """模拟 fetch 返回多行。"""
        return self._rows

    def add_row(self, row_data: dict):
        """添加模拟行。"""
        self._rows.append(row_data)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_dag_state():
    """创建模拟的 DAG 引擎状态。"""
    return {
        "plan": {
            "plan_id": "plan-123",
            "session_id": "session-456",
            "trace_id": "trace-789",
            "states": [
                {"state_id": "state-1", "order_index": 0, "responsibility": "信息收集"},
                {"state_id": "state-2", "order_index": 1, "responsibility": "数据分析"},
            ],
        },
        "cursor": 0,
        "terminated": False,
        "state_runtimes": {
            "state-1": {"status": "SUCCEEDED", "steps_completed": 2},
            "state-2": {"status": "RUNNING", "steps_completed": 1},
        },
        "executor_runtime": {
            "state_runtime": {"status": "RUNNING", "steps_completed": 1},
        },
        "budget_consumed": {"tool_calls": 3},
        "gating_suspended": False,
        "gating_pending_node_ids": [],
    }


# ===========================================================================
# SnapshotManager 测试 — 无后端
# ===========================================================================


class TestSnapshotManagerNoBackend:
    """SnapashotManager 无 PG/Redis 时的降级行为。"""

    @pytest.mark.asyncio
    async def test_init_without_backends(self):
        """验证无后端时初始化成功。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=None)
        assert mgr is not None

    @pytest.mark.asyncio
    async def test_save_snapshot_without_backends(self, mock_dag_state):
        """验证无后端时保存快照返回 ID。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=None)
        snapshot_id = await mgr.save_snapshot(
            task_id="task-1",
            dag_state=mock_dag_state,
            trigger="CHECKPOINT",
        )
        assert snapshot_id is not None
        assert len(snapshot_id) > 0

    @pytest.mark.asyncio
    async def test_load_latest_without_backends(self):
        """验证无后端时加载快照返回 None。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=None)
        result = await mgr.load_latest_snapshot("task-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots_without_backends(self):
        """验证无后端时列表查询返回空列表。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=None)
        result = await mgr.list_snapshots("task-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_save_freeze_without_redis(self):
        """验证无 Redis 时保存情绪冻结返回 False。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=None)
        result = await mgr.save_freeze_snapshot(
            task_id="task-1",
            dag_state={"key": "value"},
            esm_before="NEUTRAL",
        )
        assert result is False


# ===========================================================================
# SnapshotManager 测试 — 仅 Redis
# ===========================================================================


class TestSnapshotManagerRedisOnly:
    """SnapshotManager 仅 Redis 后端的行为。"""

    @pytest.fixture
    def mgr(self):
        return SnapshotManager(pg_pool=None, redis_client=MockRedisClient())

    @pytest.mark.asyncio
    async def test_save_and_load_with_redis(self, mgr, mock_dag_state):
        """验证 Redis 保存和加载快照。"""
        # 保存快照
        snapshot_id = await mgr.save_snapshot(
            task_id="task-redis-1",
            dag_state=mock_dag_state,
            trigger="CHECKPOINT",
        )
        assert snapshot_id is not None

        # 从 Redis 加载最新快照
        loaded = await mgr.load_latest_snapshot("task-redis-1")
        assert loaded is not None
        assert loaded["plan"]["plan_id"] == "plan-123"
        assert loaded["cursor"] == 0
        assert loaded["budget_consumed"]["tool_calls"] == 3

    @pytest.mark.asyncio
    async def test_load_nonexistent_task(self, mgr):
        """验证加载不存在的任务返回 None。"""
        result = await mgr.load_latest_snapshot("nonexistent-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_snapshot_with_redis(self, mgr, mock_dag_state):
        """验证 Redis 删除快照。"""
        await mgr.save_snapshot("task-del", mock_dag_state, "CHECKPOINT")
        await mgr.delete_snapshot("task-del")
        loaded = await mgr.load_latest_snapshot("task-del")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_freeze_save_and_load_with_redis(self, mgr):
        """验证 Redis 情绪冻结快照的保存和加载。"""

        success = await mgr.save_freeze_snapshot(
            task_id="task-freeze-1",
            dag_state={"cursor": 2, "terminated": True},
            esm_before="NEUTRAL",
        )
        assert success is True

        loaded = await mgr.load_freeze_snapshot("task-freeze-1")
        assert loaded is not None
        assert loaded["esm_before"] == "NEUTRAL"
        assert loaded["dag_state_json"]["cursor"] == 2

    @pytest.mark.asyncio
    async def test_freeze_delete_with_redis(self, mgr):
        """验证 Redis 删除情绪冻结快照。"""
        await mgr.save_freeze_snapshot("task-freeze-del", {"key": "val"}, "NEUTRAL")
        result = await mgr.delete_freeze_snapshot("task-freeze-del")
        assert result is True

        loaded = await mgr.load_freeze_snapshot("task-freeze-del")
        assert loaded is None


# ===========================================================================
# SnapshotManager 测试 — 降级行为
# ===========================================================================


class TestSnapshotManagerDegradation:
    """SnapshotManager 降级行为测试。"""

    @pytest.mark.asyncio
    async def test_redis_fallback_to_none(self, mock_dag_state):
        """验证 Redis 不可用时自动返回 None（不抛异常）。"""
        class BrokenRedis:
            def get_client(self):
                return self
            async def get(self, key):
                raise ConnectionError("Redis 连接断开")
            async def setex(self, key, ttl, value):
                raise ConnectionError("Redis 连接断开")

        mgr = SnapshotManager(pg_pool=None, redis_client=BrokenRedis())
        # 保存不应抛异常
        snapshot_id = await mgr.save_snapshot("task-broken", mock_dag_state, "CHECKPOINT")
        assert snapshot_id is not None

        # 加载应返回 None（非抛异常）
        result = await mgr.load_latest_snapshot("task-broken")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots_empty_with_redis_only(self):
        """验证仅 Redis 时列表查询返回空列表（非抛异常）。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=MockRedisClient())
        result = await mgr.list_snapshots("task-1")
        assert result == []


# ===========================================================================
# SnapshotManager 测试 — 数据序列化
# ===========================================================================


class TestSnapshotManagerSerialization:
    """快照序列化测试。"""

    @pytest.mark.asyncio
    async def test_save_with_dict_dag_state(self):
        """验证字典格式的 dag_state 保存。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=MockRedisClient())
        snap_id = await mgr.save_snapshot(
            task_id="test-dict",
            dag_state={"plan": {"plan_id": "p1"}, "cursor": 5},
            trigger="CHECKPOINT",
        )
        assert snap_id is not None

    @pytest.mark.asyncio
    async def test_save_with_pydantic_model(self, mock_dag_state):
        """验证提供了 model_dump 方法时的序列化。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=MockRedisClient())

        class MockModel:
            def model_dump(self, mode="json"):
                return {"plan": {"plan_id": "pydantic-plan"}, "cursor": 3}

        snap_id = await mgr.save_snapshot(
            task_id="test-pydantic",
            dag_state=MockModel(),
            trigger="TEST",
        )
        assert snap_id is not None

    @pytest.mark.asyncio
    async def test_save_multiple_snapshots_and_load_latest(self, mock_dag_state):
        """验证多次保存后 load_latest 返回最新版本。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=MockRedisClient())

        # 保存第一个版本
        mock_dag_state["cursor"] = 0
        await mgr.save_snapshot("task-ver", mock_dag_state, "STATE_COMPLETED")

        # 保存第二个版本（cursor 推进）
        mock_dag_state["cursor"] = 1
        await mgr.save_snapshot("task-ver", mock_dag_state, "STATE_COMPLETED")

        # 加载最新版本
        loaded = await mgr.load_latest_snapshot("task-ver")
        assert loaded["cursor"] == 1


# ===========================================================================
# 集成测试准备：mock Pydantic model
# ===========================================================================


class FakeDagEngineState:
    """模拟 DagEngineState 的 Pydantic 模型。"""
    def __init__(self, plan_id="plan-1", cursor=0, terminated=False, state_runtimes=None):
        self.plan = FakePlanDefinition(plan_id=plan_id)
        self.cursor = cursor
        self.terminated = terminated
        self.state_runtimes = state_runtimes or {}
        self.executor_runtime = {}
        self.budget_consumed = {"tool_calls": 0}
        self.termination_reason = ""
        self.termination_state_id = ""
        self.plan_replan_count = 0
        self.gating_suspended = False
        self.gating_pending_node_ids = []
        self.global_merged_context = {}
        self.disambiguated_text = ""
        self.workflow_state = {}
        self.plan_summary = {}

    def model_dump(self, mode="json"):
        return {
            "plan": {"plan_id": self.plan.plan_id, "session_id": "", "trace_id": "",
                     "states": []},
            "cursor": self.cursor,
            "terminated": self.terminated,
            "state_runtimes": self.state_runtimes,
            "executor_runtime": self.executor_runtime,
            "budget_consumed": self.budget_consumed,
            "termination_reason": self.termination_reason,
            "gating_suspended": self.gating_suspended,
            "gating_pending_node_ids": self.gating_pending_node_ids,
        }


class FakePlanDefinition:
    def __init__(self, plan_id="plan-1"):
        self.plan_id = plan_id


class TestSnapshotManagerModel:
    """验证 Pydantic 风格的模型序列化。"""

    @pytest.mark.asyncio
    async def test_pydantic_model_save_and_load(self):
        """验证 Pydantic 模型格式的快照保存和加载。"""
        mgr = SnapshotManager(pg_pool=None, redis_client=MockRedisClient())
        state = FakeDagEngineState(plan_id="pydantic-plan", cursor=2,
                                   state_runtimes={"s1": {"status": "SUCCEEDED"}})

        snap_id = await mgr.save_snapshot("task-model", state, "CHECKPOINT")
        assert snap_id is not None

        loaded = await mgr.load_latest_snapshot("task-model")
        assert loaded is not None
        assert loaded["plan"]["plan_id"] == "pydantic-plan"
        assert loaded["cursor"] == 2
