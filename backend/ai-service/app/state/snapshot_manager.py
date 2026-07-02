"""
Luna AI 快照管理器 — Plan 运行时快照的保存与恢复。

做什么：提供快照的保存、加载、列表查询和删除功能，
        同时维护 Redis 快速检查点和 PostgreSQL 持久化快照。
为什么这样做：Redis 提供毫秒级恢复，PG 提供持久的审计恢复能力。
输入输出：save_snapshot 返回快照 ID 字符串；load_latest_snapshot 返回 DagEngineState。
边界条件：Redis 不可用时降级为仅 PG 存储，不影响主链路。
异常行为：序列化/反序列化失败时记录错误并返回 None。
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id


class SnapshotManager:
    """快照管理器 — 负责 Plan 运行时快照的保存与恢复。

    做什么：提供快照的保存、加载、列表查询和删除功能，
            同时维护 Redis 快速检查点和 PostgreSQL 持久化快照。
    为什么这样做：Redis 提供毫秒级恢复，PG 提供持久的审计恢复能力。
    输入输出：save_snapshot 返回快照 ID 字符串；load_latest_snapshot 返回 DagEngineState。
    边界条件：Redis 不可用时降级为仅 PG 存储，不影响主链路。
    异常行为：序列化/反序列化失败时记录错误并返回 None。
    """

    def __init__(
        self,
        pg_pool: Any = None,
        redis_client: Any = None,
        checkpoint_ttl: int = 86400,       # 检查点 TTL（24h）
        snapshot_ttl: int = 604800,        # 快照缓存 TTL（7d）
    ):
        """初始化快照管理器。

        参数:
            pg_pool: PostgreSQL 连接池（用于持久化快照）。
            redis_client: Redis 客户端实例（用于短时效检查点）。
            checkpoint_ttl: 检查点 TTL（秒）。
            snapshot_ttl: 快照缓存 TTL（秒）。
        """
        self._pg = pg_pool
        self._redis = redis_client
        self._checkpoint_ttl = checkpoint_ttl
        self._snapshot_ttl = snapshot_ttl

    async def save_snapshot(
        self,
        task_id: str,
        dag_state: Any,               # DagEngineState 实例
        trigger: str,
        session_id: str = "",
        trace_id: str = "",
        plan_id: str = "",
        snapshot_version: int | None = None,
        gating_snapshot: dict | None = None,
        task_status: str = "RUNNING",
    ) -> str:
        """保存全量快照到 PostgreSQL，同时保存轻量检查点到 Redis。

        做什么：
        1. 序列化 DagEngineState 为 JSON
        2. 写入 PostgreSQL task_snapshots 表
        3. 写入 Redis task_state:{task_id}（24h TTL）
        4. 返回快照 ID

        参数:
            task_id: 任务 ID。
            dag_state: 当前 DAG 引擎状态（DagEngineState 实例或可序列化对象）。
            trigger: 触发保存的事件名（TIMEOUT / CRASH / CHECKPOINT 等）。
            session_id: 会话 ID。
            trace_id: 追踪 ID。
            plan_id: Plan ID。
            snapshot_version: 快照版本号，None 时自动递增。
            gating_snapshot: Gating 相关的额外快照数据。
            task_status: 任务状态字符串。

        返回:
            快照 ID 字符串。
        """
        snapshot_id = generate_string_id()

        # 获取下一个版本号
        version = snapshot_version
        if version is None:
            version = await self._get_next_version(task_id)

        # 尝试序列化 DagEngineState
        try:
            if hasattr(dag_state, "model_dump"):
                serialized = dag_state.model_dump(mode="json")
            elif hasattr(dag_state, "dict"):
                serialized = dag_state.dict()
            elif isinstance(dag_state, dict):
                serialized = dag_state
            else:
                serialized = str(dag_state)
        except Exception as exc:
            logger.error(
                f"SnapshotManager: 序列化 dag_state 失败 "
                f"task={task_id}, error={exc}"
            )
            serialized = {"error": str(exc)}

        # 提取元数据（如果 serialized 是字典）
        actual_session_id = session_id or serialized.get("plan", {}).get("session_id", "")
        actual_trace_id = trace_id or serialized.get("plan", {}).get("trace_id", "")
        actual_plan_id = plan_id or serialized.get("plan", {}).get("plan_id", "")

        # 提取 executor_runtime
        executor_runtime = serialized.get("executor_runtime", {})

        # === PostgreSQL 持久化 ===
        pg_success = False
        if self._pg is not None:
            try:
                await self._pg.execute(
                    """INSERT INTO task_snapshots
                       (id, task_id, session_id, trace_id, plan_id, task_status,
                        dag_engine_state, executor_runtime, gating_snapshot,
                        snapshot_version, trigger_event, saved_at_ms)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                    snapshot_id,
                    task_id,
                    actual_session_id,
                    actual_trace_id,
                    actual_plan_id,
                    task_status,
                    json.dumps(serialized, ensure_ascii=False, default=str),
                    json.dumps(executor_runtime, ensure_ascii=False, default=str),
                    json.dumps(gating_snapshot or {}, ensure_ascii=False, default=str),
                    version,
                    trigger,
                    int(time.time() * 1000),
                )
                pg_success = True
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: PG 写入快照失败 "
                    f"task={task_id}, error={exc}"
                )

        # === Redis 轻量检查点 ===
        if self._redis is not None:
            try:
                redis_key = f"task_state:{task_id}"
                client = self._get_redis_client()
                await client.setex(
                    redis_key,
                    self._checkpoint_ttl,
                    json.dumps({
                        "task_status": task_status,
                        "dag_state_json": serialized,
                        "saved_at_ms": int(time.time() * 1000),
                        "trigger_event": trigger,
                    }, ensure_ascii=False, default=str),
                )
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: Redis 写入检查点失败 "
                    f"task={task_id}, error={exc}"
                )

        # === Redis 全量快照缓存（用于审计回放）===
        if self._redis is not None and pg_success:
            try:
                cache_key = f"task_snapshot:{task_id}:v{version}"
                client = self._get_redis_client()
                await client.setex(
                    cache_key,
                    self._snapshot_ttl,
                    json.dumps({
                        "snapshot_id": snapshot_id,
                        "version": version,
                        "task_status": task_status,
                        "dag_state_json": serialized,
                        "gating_snapshot": gating_snapshot or {},
                        "saved_at_ms": int(time.time() * 1000),
                    }, ensure_ascii=False, default=str),
                )
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: Redis 写入全量快照缓存失败 "
                    f"task={task_id}, error={exc}"
                )

        logger.info(
            f"SnapshotManager: 保存快照成功 "
            f"task={task_id}, version={version}, trigger={trigger}"
        )
        return snapshot_id

    async def load_latest_snapshot(
        self,
        task_id: str,
    ) -> Any | None:
        """加载最新的快照。

        恢复优先级：
        1. 先检查 Redis（快速恢复，毫秒级）
        2. Redis 不存在则从 PostgreSQL 加载最新版本
        3. 返回反序列化后的 DagEngineState，或 None（无可用快照）

        参数:
            task_id: 任务 ID。

        返回:
            DagEngineState 实例（需要调用方自行反序列化为具体类型），
            或序列化字典，或 None（无可用快照）。
        """
        # 1. 尝试 Redis
        if self._redis is not None:
            try:
                redis_key = f"task_state:{task_id}"
                client = self._get_redis_client()
                raw = await client.get(redis_key)
                if raw:
                    data = json.loads(raw)
                    dag_state_json = data.get("dag_state_json")
                    if dag_state_json:
                        logger.info(
                            f"SnapshotManager: 从 Redis 恢复快照成功 "
                            f"task={task_id}"
                        )
                        return dag_state_json
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: Redis 恢复失败: {exc}"
                )

        # 2. 回退到 PG
        if self._pg is not None:
            try:
                row = await self._pg.fetchrow(
                    """SELECT dag_engine_state, snapshot_version
                       FROM task_snapshots
                       WHERE task_id = $1
                       ORDER BY snapshot_version DESC
                       LIMIT 1""",
                    task_id,
                )
                if row and row["dag_engine_state"]:
                    dag_state_json = row["dag_engine_state"]
                    if isinstance(dag_state_json, str):
                        dag_state_json = json.loads(dag_state_json)

                    logger.info(
                        f"SnapshotManager: 从 PG 恢复快照成功 "
                        f"task={task_id}, version={row.get('snapshot_version', '?')}"
                    )
                    return dag_state_json
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: PG 恢复失败: {exc}"
                )

        logger.warning(
            f"SnapshotManager: 无可用快照 task={task_id}"
        )
        return None

    async def list_snapshots(self, task_id: str) -> list[dict[str, Any]]:
        """列出指定任务的所有快照版本（用于审计回放）。

        参数:
            task_id: 任务 ID。

        返回:
            快照元数据字典列表（不含 dag_engine_state 全量数据），
            按 snapshot_version 降序排列。
        """
        if self._pg is None:
            return []

        try:
            rows = await self._pg.fetch(
                """SELECT id, snapshot_version, trigger_event,
                          saved_at_ms, created_at, task_status
                   FROM task_snapshots
                   WHERE task_id = $1
                   ORDER BY snapshot_version DESC""",
                task_id,
            )
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning(
                f"SnapshotManager: 列出快照失败 task={task_id}, error={exc}"
            )
            return []

    async def load_snapshot_by_version(
        self,
        task_id: str,
        version: int,
    ) -> Any | None:
        """按版本号加载指定快照。

        做什么：加载指定版本的快照数据，用于审计回放时的历史状态查看。

        参数:
            task_id: 任务 ID。
            version: 快照版本号。

        返回:
            dag_engine_state 的序列化字典，或 None。
        """
        if self._pg is None:
            return None

        try:
            row = await self._pg.fetchrow(
                """SELECT dag_engine_state
                   FROM task_snapshots
                   WHERE task_id = $1 AND snapshot_version = $2""",
                task_id,
                version,
            )
            if row and row["dag_engine_state"]:
                dag_state_json = row["dag_engine_state"]
                if isinstance(dag_state_json, str):
                    dag_state_json = json.loads(dag_state_json)
                return dag_state_json
        except Exception as exc:
            logger.warning(
                f"SnapshotManager: 按版本加载快照失败 "
                f"task={task_id}, version={version}, error={exc}"
            )
        return None

    async def delete_snapshot(self, task_id: str) -> None:
        """任务正常完成后清理所有快照资源。

        做什么：
        1. 删除 PostgreSQL 中该任务的所有快照
        2. 删除 Redis 中该任务的检查点和缓存

        参数:
            task_id: 任务 ID。
        """
        if self._pg is not None:
            try:
                await self._pg.execute(
                    "DELETE FROM task_snapshots WHERE task_id = $1",
                    task_id,
                )
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: 删除 PG 快照失败 "
                    f"task={task_id}, error={exc}"
                )

        if self._redis is not None:
            try:
                client = self._get_redis_client()
                # 清理检查点
                await client.delete(f"task_state:{task_id}")
                # 清理全量快照缓存（通过模式匹配查找）
                cursor = 0
                while True:
                    cursor, keys = await client.scan(
                        cursor=cursor,
                        match=f"task_snapshot:{task_id}:*",
                        count=100,
                    )
                    if keys:
                        await client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as exc:
                logger.warning(
                    f"SnapshotManager: 删除 Redis 快照失败 "
                    f"task={task_id}, error={exc}"
                )

        logger.info(
            f"SnapshotManager: 清理快照 task={task_id}"
        )

    async def save_freeze_snapshot(
        self,
        task_id: str,
        dag_state: Any,
        esm_before: str,
    ) -> bool:
        """保存情绪冻结快照。

        做什么：当 ESM 检测到高危情绪时，保存当前的 WSM 快照和情绪状态，
                用于情绪恢复后 Resume。

        参数:
            task_id: 任务 ID。
            dag_state: 冻结时的 DAG 引擎状态。
            esm_before: 冻结前的情绪状态。

        返回:
            True 表示保存成功。
        """
        if self._redis is None:
            return False

        try:
            # 序列化 dag_state
            if hasattr(dag_state, "model_dump"):
                serialized = dag_state.model_dump(mode="json")
            elif hasattr(dag_state, "dict"):
                serialized = dag_state.dict()
            elif isinstance(dag_state, dict):
                serialized = dag_state
            else:
                serialized = str(dag_state)

            freeze_data = {
                "dag_state_json": serialized,
                "esm_before": esm_before,
                "saved_at_ms": int(time.time() * 1000),
            }

            client = self._get_redis_client()
            await client.setex(
                f"task_freeze:{task_id}",
                86400,  # 24h TTL
                json.dumps(freeze_data, ensure_ascii=False, default=str),
            )
            logger.info(
                f"SnapshotManager: 保存情绪冻结快照 task={task_id}, esm={esm_before}"
            )
            return True
        except Exception as exc:
            logger.warning(
                f"SnapshotManager: 保存情绪冻结快照失败 "
                f"task={task_id}, error={exc}"
            )
            return False

    async def load_freeze_snapshot(
        self,
        task_id: str,
    ) -> dict[str, Any] | None:
        """加载情绪冻结快照。

        参数:
            task_id: 任务 ID。

        返回:
            冻结快照字典，或 None。
        """
        if self._redis is None:
            return None

        try:
            client = self._get_redis_client()
            raw = await client.get(f"task_freeze:{task_id}")
            if not raw:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning(
                f"SnapshotManager: 加载情绪冻结快照失败 "
                f"task={task_id}, error={exc}"
            )
            return None

    async def delete_freeze_snapshot(self, task_id: str) -> bool:
        """删除情绪冻结快照。

        参数:
            task_id: 任务 ID。

        返回:
            True 表示删除成功。
        """
        if self._redis is None:
            return False

        try:
            client = self._get_redis_client()
            await client.delete(f"task_freeze:{task_id}")
            return True
        except Exception:
            return False

    async def _get_next_version(self, task_id: str) -> int:
        """获取下一个快照版本号。

        做什么：查询 PostgreSQL 中该任务的最大快照版本号，返回 +1。
        为什么这样做：版本号自动递增，不依赖客户端传入。

        参数:
            task_id: 任务 ID。

        返回:
            下一个版本号（int）。无历史版本时返回 1。
        """
        if self._pg is None:
            return 1

        try:
            row = await self._pg.fetchrow(
                "SELECT COALESCE(MAX(snapshot_version), 0) + 1 AS next_ver "
                "FROM task_snapshots WHERE task_id = $1",
                task_id,
            )
            return row["next_ver"] if row else 1
        except Exception:
            return 1

    async def set_task_status(
        self,
        task_id: str,
        status: str,
        trace_id: str = "",
    ) -> bool:
        """轻量级更新 Redis 中任务状态。

        做什么：更新 Redis task_state:{task_id} 中的 task_status 字段。
                不修改 DagEngineState 全量数据，仅更新状态标记。
                用于外部命令（暂停/取消/恢复）的轻量级状态更新。

        参数:
            task_id: 任务 ID。
            status: 目标状态字符串（如 PAUSED / TERMINATED / RUNNING）。
            trace_id: 追踪 ID（可选）。

        返回:
            True 表示更新成功，False 表示 Redis 不可用或更新失败。
        """
        if self._redis is None:
            logger.warning(
                f"SnapshotManager.set_task_status: Redis 不可用，"
                f"跳过状态更新 task={task_id} status={status}"
            )
            return False

        try:
            client = self._get_redis_client()
            redis_key = f"task_state:{task_id}"
            raw = await client.get(redis_key)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                data["task_status"] = status
                if trace_id:
                    data["trace_id"] = trace_id
                await client.setex(
                    redis_key,
                    self._checkpoint_ttl,
                    json.dumps(data, ensure_ascii=False, default=str),
                )
            else:
                # 无已有快照，写入最小状态记录
                await client.setex(
                    redis_key,
                    self._checkpoint_ttl,
                    json.dumps({
                        "task_status": status,
                        "trace_id": trace_id,
                        "saved_at_ms": int(time.time() * 1000),
                    }, ensure_ascii=False, default=str),
                )

            logger.info(
                f"SnapshotManager: 更新任务状态 task={task_id} "
                f"status={status} trace_id={trace_id}"
            )
            return True
        except Exception as exc:
            logger.warning(
                f"SnapshotManager: 更新任务状态失败 "
                f"task={task_id} status={status} error={exc}"
            )
            return False

    def _get_redis_client(self) -> Any:
        """获取原始 Redis 客户端。

        做什么：兼容两种 Redis 客户端封装方式：
        1. 传递了 get_client() 方法的封装类（如 RedisClient）
        2. 传递了原始 Redis 客户端实例

        返回:
            原始 Redis 客户端（具有 get/setex/delete 等方法）。
        """
        if self._redis is None:
            raise RuntimeError("Redis 客户端未初始化")
        # 兼容封装类的 get_client() 方法
        if hasattr(self._redis, "get_client"):
            return self._redis.get_client()
        return self._redis
