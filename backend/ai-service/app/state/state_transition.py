"""
Luna AI 状态跃迁管理模块 — 跃迁审计日志持久化。

做什么：记录所有任务状态跃迁事件到 PostgreSQL 的 state_transition_logs 表，
        提供跃迁历史的审计查询能力。
为什么这样做：agent.md 要求所有状态迁移必须显式记录 from -> to、触发原因、trace_id、task_id，
             实现完整的可审计性。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.logger import logger
from app.state.task_state_machine import TaskStatus
from app.utils.snowflake import generate_string_id


class StateTransitionLog:
    """状态跃迁审计日志 — 单条跃迁记录。

    做什么：封装单条状态跃迁的完整信息，支持序列化为字典用于持久化。
    为什么这样做：统一的数据结构确保跃迁日志格式一致，便于审计回放。
    输入输出：to_dict() 返回字典格式，适用于数据库写入。
    边界条件：trigger_type 限定为预定义枚举字符串。
    """

    # 允许的触发类型常量
    TRIGGER_NORMAL = "NORMAL_ADVANCE"
    TRIGGER_EMOTION = "EMOTION_INTERRUPT"
    TRIGGER_RESUME = "RESUME"
    TRIGGER_FALLBACK = "FALLBACK"
    TRIGGER_TIMEOUT = "TIMEOUT"
    TRIGGER_USER_CANCEL = "USER_CANCEL"
    TRIGGER_GATING = "GATING"
    TRIGGER_BUDGET = "BUDGET_EXHAUSTED"
    TRIGGER_RECOVERY = "RECOVERY"
    TRIGGER_CRASH = "CRASH"

    def __init__(
        self,
        session_id: str,
        prev_status: TaskStatus | str,
        next_status: TaskStatus | str,
        trigger_type: str = TRIGGER_NORMAL,
        transition_reason: str = "",
        task_id: str = "",
        turn_id: str = "",
        trace_id: str = "",
        prev_esm: str = "",
        next_esm: str = "",
        log_id: str | None = None,
    ):
        """初始化跃迁日志记录。

        参数:
            session_id: 会话 ID。
            prev_status: 跃迁前状态（TaskStatus 枚举值或字符串）。
            next_status: 跃迁后状态（TaskStatus 枚举值或字符串）。
            trigger_type: 触发类型，限定为 TRIGGER_* 常量。
            transition_reason: 跃迁原因描述。
            task_id: 任务 ID（可选）。
            turn_id: 轮次 ID（可选）。
            trace_id: 追踪 ID（可选）。
            prev_esm: 跃迁前情绪状态（可选）。
            next_esm: 跃迁后情绪状态（可选）。
            log_id: 日志 ID，不传时自动生成雪花 ID。
        """
        self.log_id = log_id or generate_string_id()
        self.session_id = session_id
        self.task_id = task_id
        self.turn_id = turn_id
        self.prev_wsm = prev_status.value if isinstance(prev_status, TaskStatus) else prev_status
        self.next_wsm = next_status.value if isinstance(next_status, TaskStatus) else next_status
        self.trigger_type = trigger_type
        self.transition_reason = transition_reason
        self.trace_id = trace_id
        self.prev_esm = prev_esm
        self.next_esm = next_esm
        self.created_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """转为字典格式（用于数据库写入）。"""
        return {
            "id": self.log_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "turn_id": self.turn_id,
            "prev_wsm": self.prev_wsm,
            "next_wsm": self.next_wsm,
            "prev_esm": self.prev_esm,
            "next_esm": self.next_esm,
            "trigger_type": self.trigger_type,
            "transition_reason": self.transition_reason,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
        }


class StateTransitionManager:
    """状态跃迁管理器 — 跃迁审计日志的持久化与查询。

    做什么：提供跃迁日志的写入、批量写入和按条件查询功能。
    为什么这样做：跃迁日志统一通过此管理器持久化，确保日志格式一致。
    输入输出：
        - log_transition(): 写入单条跃迁日志。
        - query_logs(): 按条件查询跃迁日志列表。
        - delete_logs_by_session(): 删除指定会话的所有跃迁日志。
    边界条件：PG 连接不可用时降级为仅日志告警，不抛出异常。
    """

    def __init__(self, pg_pool: Any = None):
        """初始化。

        参数:
            pg_pool: PostgreSQL 连接池（AsyncEngine 或类似对象）。
                    为 None 时只记录日志，不做持久化。
        """
        self._pg = pg_pool

    async def log_transition(
        self,
        session_id: str,
        prev_status: TaskStatus | str,
        next_status: TaskStatus | str,
        trigger_type: str = StateTransitionLog.TRIGGER_NORMAL,
        transition_reason: str = "",
        task_id: str = "",
        turn_id: str = "",
        trace_id: str = "",
        prev_esm: str = "",
        next_esm: str = "",
    ) -> str:
        """写入单条状态跃迁日志。

        做什么：创建并持久化一条状态跃迁审计日志。
        为什么这样做：每次状态变更都记录，满足 agent.md 可审计性要求。

        参数:
            同上 __init__。

        返回:
            日志 ID 字符串；PG 不可用时返回空字符串。
        """
        log_entry = StateTransitionLog(
            session_id=session_id,
            prev_status=prev_status,
            next_status=next_status,
            trigger_type=trigger_type,
            transition_reason=transition_reason,
            task_id=task_id,
            turn_id=turn_id,
            trace_id=trace_id,
            prev_esm=prev_esm,
            next_esm=next_esm,
        )

        # 持久化到 PG
        if self._pg is not None:
            try:
                await self._pg.execute(
                    """INSERT INTO state_transition_logs
                       (id, session_id, task_id, turn_id,
                        prev_wsm, next_wsm, prev_esm, next_esm,
                        trigger_type, transition_reason, trace_id, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                    log_entry.log_id,
                    log_entry.session_id,
                    log_entry.task_id,
                    log_entry.turn_id,
                    log_entry.prev_wsm,
                    log_entry.next_wsm,
                    log_entry.prev_esm,
                    log_entry.next_esm,
                    log_entry.trigger_type,
                    log_entry.transition_reason,
                    log_entry.trace_id,
                    log_entry.created_at,
                )
            except Exception as exc:
                logger.warning(
                    f"StateTransitionManager: 写入跃迁日志失败 "
                    f"session={session_id}, error={exc}"
                )

        logger.info(
            f"StateTransitionManager: 跃迁日志已记录 "
            f"{prev_status} -> {next_status} "
            f"trigger={trigger_type} "
            f"[TraceID:{trace_id}] [TaskID:{task_id}]"
        )

        return log_entry.log_id

    async def query_logs(
        self,
        session_id: str = "",
        task_id: str = "",
        trace_id: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """查询跃迁日志。

        做什么：按会话 ID、任务 ID 或追踪 ID 查询跃迁日志列表。
        为什么这样做：用于审计回放和调试。

        参数:
            session_id: 会话 ID（可选过滤条件）。
            task_id: 任务 ID（可选过滤条件）。
            trace_id: 追踪 ID（可选过滤条件）。
            limit: 返回条数上限。
            offset: 分页偏移。

        返回:
            跃迁日志字典列表，按 created_at 降序排列。
        """
        if self._pg is None:
            return []

        try:
            conditions = []
            params: list[Any] = []
            param_idx = 1

            if session_id:
                conditions.append(f"session_id = ${param_idx}")
                params.append(session_id)
                param_idx += 1
            if task_id:
                conditions.append(f"task_id = ${param_idx}")
                params.append(task_id)
                param_idx += 1
            if trace_id:
                conditions.append(f"trace_id = ${param_idx}")
                params.append(trace_id)
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            query = f"""SELECT id, session_id, task_id, turn_id,
                               prev_wsm, next_wsm, prev_esm, next_esm,
                               trigger_type, transition_reason, trace_id, created_at
                        FROM state_transition_logs
                        WHERE {where_clause}
                        ORDER BY created_at DESC
                        LIMIT ${param_idx} OFFSET ${param_idx + 1}"""
            params.append(limit)
            params.append(offset)

            rows = await self._pg.fetch(query, *params)
            return [dict(row) for row in rows]

        except Exception as exc:
            logger.warning(
                f"StateTransitionManager: 查询跃迁日志失败 "
                f"session={session_id}, error={exc}"
            )
            return []

    async def delete_logs_by_session(self, session_id: str) -> bool:
        """删除指定会话的所有跃迁日志。

        做什么：会话结束时清理关联的跃迁日志。
        为什么这样做：避免长期积累的日志影响查询性能。

        参数:
            session_id: 会话 ID。

        返回:
            True 表示删除成功。
        """
        if self._pg is None:
            return False

        try:
            await self._pg.execute(
                "DELETE FROM state_transition_logs WHERE session_id = $1",
                session_id,
            )
            logger.info(
                f"StateTransitionManager: 清理跃迁日志 session={session_id}"
            )
            return True
        except Exception as exc:
            logger.warning(
                f"StateTransitionManager: 清理跃迁日志失败 "
                f"session={session_id}, error={exc}"
            )
            return False
