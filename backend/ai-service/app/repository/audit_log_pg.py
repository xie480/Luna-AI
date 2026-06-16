"""
Luna AI 审计日志仓储层。

做什么：提供 audit_logs 表的 CRUD 操作，包括创建审计记录、
        更新审批状态、查询待处理请求等。
        所有审计记录不可删除，只能更新状态，保证审计链的完整性。

为什么这样做：根据 agent.md 6.4 安全与治理规范，所有关键链路必须可审计。
             audit_logs 表是安全事件的 Single Source of Truth。
             所有工具调用（特别是高风险操作）必须记录完整的生命周期。

输入输出：
    - create(): 创建审计日志记录，返回 bool。
    - update_status(): 更新审计状态（PENDING → APPROVED/REJECTED/TIMEOUT）。
    - get_pending(): 获取当前所有 PENDING 状态的请求。
    - get_by_id(): 根据 audit_log_id 查询单条记录。
    - get_pending_count(): 获取当前 PENDING 请求数量。

边界条件：
    - 创建时 status 默认为 PENDING。
    - 状态更新后 updated_at 自动刷新。
    - 不支持物理删除操作，保证审计完整性。
    - 所有 ID 字段使用雪花算法生成的字符串。

异常行为：
    - 查询失败时返回 None 或空列表，不抛出异常。
    - 更新不存在记录时返回 False。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.gating.types import AuthStatus
from app.infrastructure.postgres import PostgresClient
from app.logger import logger


class AuditLogPGRepo:
    """审计日志 PostgreSQL 仓储层。

    做什么：封装 audit_logs 表的所有数据库操作。
    为什么这样做：审计记录操作集中在此，保证 SQL 语句的统一管理。
                 每次操作独立创建会话，避免会话生命周期管理问题。
    """

    def __init__(self, pg_client: PostgresClient) -> None:
        """
        初始化审计日志仓储。

        输入：pg_client - PostgreSQL 客户端实例。
              遵循与其他仓库（如 ErrorLogPGRepo）相同的构造模式。
        """
        self.pg_client = pg_client

    async def create(
        self,
        audit_log_id: str,
        tool_id: str,
        tool_name: str,
        risk_level: str,
        reason: str,
        arguments: dict,
        trace_id: str,
        task_id: str,
        goal: str = "",
        agent_output: str = "",
        user_id: str = "local_default_user",
    ) -> bool:
        """
        创建审计日志记录。

        做什么：记录一次工具调用的审计日志，初始状态为 PENDING。
        为什么这样做：所有高危工具调用必须记录审计日志，作为安全事件的 SSOT。
        输入：审计日志所需的全部字段。
        输出：bool - 创建成功返回 True，失败返回 False。
        边界条件：
            - status 硬编码为 PENDING，不允许外部传入。
            - arguments 以 JSON 格式存储。
        异常行为：数据库异常时记录错误日志并返回 False。
        """
        from sqlalchemy import text

        try:
            async with self.pg_client.session_factory() as session:
                now = datetime.now(timezone.utc)
                query = """
                    INSERT INTO audit_logs (
                        id, user_id, tool_id, tool_name, risk_level,
                        reason, arguments, goal, agent_output,
                        status, trace_id, task_id, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :tool_id, :tool_name, :risk_level,
                        :reason, :arguments::jsonb, :goal, :agent_output,
                        :status, :trace_id, :task_id, :created_at, :updated_at
                    )
                """
                await session.execute(
                    text(query),
                    {
                        "id": audit_log_id,
                        "user_id": user_id,
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "risk_level": risk_level,
                        "reason": reason,
                        "arguments": arguments,
                        "goal": goal,
                        "agent_output": agent_output,
                        "status": AuthStatus.PENDING.value,
                        "trace_id": trace_id,
                        "task_id": task_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                await session.commit()

            logger.info(
                f"[AuditLog] 创建审计记录成功 audit_log_id={audit_log_id} "
                f"tool={tool_name} risk={risk_level} trace_id={trace_id}"
            )
            return True
        except Exception as e:
            logger.error(
                f"[AuditLog] 创建审计记录失败 audit_log_id={audit_log_id} "
                f"tool={tool_name} error={e}"
            )
            return False

    async def update_status(
        self,
        audit_log_id: str,
        new_status: AuthStatus,
        user_feedback: str = "",
    ) -> bool:
        """
        更新审计日志状态。

        做什么：审批流程推进时更新审计记录的状态。
                例如 PENDING → APPROVED、PENDING → REJECTED。
        为什么这样做：审计记录必须跟踪完整的审批生命周期，
                     不允许跳过中间状态。
        输入：
            - audit_log_id: 要更新的审计记录 ID。
            - new_status: 目标状态。
            - user_feedback: 用户反馈理由（可选）。
        输出：bool - 更新成功返回 True，失败返回 False。
        边界条件：
            - 只能更新 PENDING 状态的记录（通过 WHERE status = :old_status 保证）。
            - updated_at 自动刷新为当前时间。
            - responded_at 在用户响应时设置。
        异常行为：找不到记录或数据库异常时返回 False。
        """
        from sqlalchemy import text

        try:
            async with self.pg_client.session_factory() as session:
                now = datetime.now(timezone.utc)
                query = """
                    UPDATE audit_logs
                    SET status = :status,
                        user_feedback = :user_feedback,
                        updated_at = :updated_at,
                        responded_at = CASE
                            WHEN :responded_at IS NOT NULL AND status = :old_status
                            THEN :responded_at
                            ELSE responded_at
                        END
                    WHERE id = :id AND status = :old_status
                """
                result = await session.execute(
                    text(query),
                    {
                        "id": audit_log_id,
                        "status": new_status.value,
                        "old_status": AuthStatus.PENDING.value,
                        "user_feedback": user_feedback,
                        "updated_at": now,
                        "responded_at": now
                        if new_status in (AuthStatus.APPROVED, AuthStatus.REJECTED)
                        else None,
                    },
                )
                await session.commit()
                if result.rowcount > 0:
                    logger.info(
                        f"[AuditLog] 更新审计状态成功 audit_log_id={audit_log_id} "
                        f"new_status={new_status.value}"
                    )
                    return True
                else:
                    logger.warning(
                        f"[AuditLog] 更新审计状态失败（记录不存在或状态非 PENDING）"
                        f" audit_log_id={audit_log_id} new_status={new_status.value}"
                    )
                    return False
        except Exception as e:
            logger.error(
                f"[AuditLog] 更新审计状态异常 audit_log_id={audit_log_id} "
                f"new_status={new_status.value} error={e}"
            )
            return False

    async def get_by_id(self, audit_log_id: str) -> Optional[dict]:
        """
        根据审计日志 ID 查询记录。

        做什么：查询单条审计日志的完整信息。
        输入：audit_log_id - 审计日志记录 ID。
        输出：dict | None - 查询成功返回字典，未找到返回 None。
        边界条件：返回的字典包含所有字段，arguments 已从 JSON 解析为 dict。
        """
        from sqlalchemy import text

        try:
            async with self.pg_client.session_factory() as session:
                query = text("SELECT * FROM audit_logs WHERE id = :id")
                result = await session.execute(query, {"id": audit_log_id})
                row = result.fetchone()
                if row:
                    return dict(row._mapping)
                return None
        except Exception as e:
            logger.error(
                f"[AuditLog] 查询审计记录失败 audit_log_id={audit_log_id} error={e}"
            )
            return None

    async def get_pending(self) -> list[dict]:
        """
        获取所有 PENDING 状态的审计日志记录。

        做什么：查询当前所有等待用户审批的请求列表。
                在断线重连状态同步时调用，返回给前端重建审批队列。
        为什么这样做：根据 agent.md 可恢复原则，系统崩溃后必须能从数据库
                     重建当前 PENDING 状态，确保审批流程不丢失。
        输出：list[dict] - PENDING 状态的审计记录列表。
        边界条件：
            - 只返回 status = 'PENDING' 的记录。
            - 按 created_at 升序排列（FIFO 队列顺序）。
            - 没有 PENDING 记录时返回空列表。
        """
        from sqlalchemy import text

        try:
            async with self.pg_client.session_factory() as session:
                query = text(
                    "SELECT * FROM audit_logs WHERE status = :status "
                    "ORDER BY id ASC"
                )
                result = await session.execute(
                    query, {"status": AuthStatus.PENDING.value}
                )
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.error(f"[AuditLog] 查询 PENDING 审计记录失败 error={e}")
            return []

    async def get_pending_count(self) -> int:
        """
        获取当前 PENDING 状态记录数量。

        做什么：返回当前待处理审批请求的数量。
        为什么这样做：用于调试面板显示，或触发超时扫描前的快速检测。
        输出：int - PENDING 记录数量。
        """
        from sqlalchemy import text

        try:
            async with self.pg_client.session_factory() as session:
                query = text(
                    "SELECT COUNT(*) as cnt FROM audit_logs "
                    "WHERE status = :status"
                )
                result = await session.execute(
                    query, {"status": AuthStatus.PENDING.value}
                )
                row = result.fetchone()
                return row.cnt if row else 0
        except Exception as e:
            logger.error(f"[AuditLog] 查询 PENDING 记录数量失败 error={e}")
            return 0
