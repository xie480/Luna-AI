"""
Luna AI Gating 模块：核心权限网关服务。

做什么：Phase 13 权限治理与前端 Gating 的后端核心服务。
        提供工具调用拦截（Intercept）、用户审批处理（Approval/Rejection）、
        超时自动拒绝（Timeout）、断线重连状态同步（Reconnect Sync）等能力。
        是 AI 主动行为的安全闸门，确保所有高危操作必须经过用户显式确认。

为什么这样做：根据 agent.md 6.4 安全与治理规范：
    1. AI 主动发起的任何涉及修改/删除文件、网络请求等高风险动作，
       Python 必须强行挂起任务并等待用户授权。
    2. Python 是唯一的 Single Source of Truth，前端仅作为投影视图，
       不持有任何审批状态。
    3. 所有关键链路必须可审计，记录完整的审批生命周期。

核心流程：
    1. Intercept: MCP 执行网关在调用 L2/L3 工具前，调用 GatingService.create_auth_request()
       创建审批请求 → 写入 PG audit_logs → 写入 Redis 队列 → 通过 SSE 推送 EVT_TOOL_AUTH_REQUIRED。
    2. Approval: 用户在前端弹窗中点击"同意" → 前端发送 CMD_TOOL_AUTH_RESPONSE →
       后端解析 → 调用 GatingService.approve_request() → 更新 PG 状态 →
       移除 Redis 队列 → 通过 callback 通知 DAG 引擎放行。
    3. Rejection: 同上，但用户点击"拒绝" → 调用 reject_request() → 阻断执行。
    4. Timeout: 后台 GatingTimeoutScheduler 扫描 → 标记超时 → 触发回调。
    5. Reconnect: 前端断线重连后发送 CMD_SYNC_INIT_STATE → 后端查询所有 PENDING 状态 →
       通过 SSE 批量推送给前端重建队列。

边界条件：
    - 同一 tool_id 在同一 task_id 下不可重复创建审批请求（防重）。
    - 已 APPROVED/REJECTED/TIMEOUT 的请求不可再次操作（幂等）。
    - Redis 中的审批状态仅作为快速查询缓存，PG audit_logs 是真实 SSOT。
    - 所有 ID 字段使用雪花算法生成。
    - 默认超时时间 300 秒（5 分钟），可通过 constructor 配置。

异常行为：
    - 数据库写入失败时返回 False，由调用方决定降级策略。
    - SSE 推送失败不影响审批请求的创建，仅记录警告日志。
    - 回调执行异常由调用方（DAG 引擎）自行处理。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from app.gating.scheduler import GatingTimeoutScheduler
from app.gating.types import (
    AuthAction,
    AuthRequestPayload,
    AuthResponsePayload,
    AuthStatus,
    GatingEventType,
    SyncInitStatePayload,
)
from app.logger import logger
from app.repository.audit_log_pg import AuditLogPGRepo
from app.utils.snowflake import generate_string_id


# ============================================================
# Redis Key 常量
# ============================================================

# Redis 中 PENDING 审批请求的集合 Key
REDIS_GATING_PENDING_KEY = "gating:pending_requests"

# 单个审批请求的 Hash Key 前缀
REDIS_GATING_REQUEST_PREFIX = "gating:request:"


class GatingService:
    """权限网关核心服务。

    做什么：管理工具调用的审批全生命周期：拦截 → 推送 → 等待 → 响应 → 放行/阻断。
            集成 SSE 推送、PG 审计、Redis 缓存、超时检测和回调机制。
    为什么这样做：集中管理所有权限审批操作，确保一致性、可审计性和可恢复性。
    输入输出：
        - create_auth_request(): 创建审批请求。返回 (success, auth_request)。
        - approve_request(): 批准请求。返回 bool。
        - reject_request(): 拒绝请求。返回 bool。
        - sync_init_state(): 同步当前所有 PENDING 请求。返回 SyncInitStatePayload。
        - get_pending_count(): 获取当前 PENDING 请求数量。返回 int。
        - start_timeout_scheduler(): 启动后台超时检测。返回 None。
        - stop_timeout_scheduler(): 停止后台超时检测。返回 None。
        - set_approve_callback(): 设置审批成功回调。
        - set_reject_callback(): 设置拒绝回调。
        - set_timeout_callback(): 设置超时回调。
    """

    def __init__(
        self,
        audit_repo: AuditLogPGRepo,
        redis_client=None,
        sse_manager=None,
        timeout_seconds: int = 300,
    ) -> None:
        """初始化 GatingService。

        输入：
            - audit_repo: 审计日志仓储实例（必选），用于 PG 持久化。
            - redis_client: Redis 客户端实例（可选），用于快速状态缓存。
            - sse_manager: SSE 管理器实例（可选），用于向前端推送事件。
            - timeout_seconds: 超时阈值秒数。默认 300 秒（5 分钟）。
        为什么这样做：通过依赖注入解耦，允许在单元测试中 Mock 仓储层和网络层。
        """
        self._audit_repo: AuditLogPGRepo = audit_repo
        self._redis_client = redis_client
        self._sse_manager = sse_manager

        # 回调注册表
        self._approve_callbacks: list[Callable] = []
        self._reject_callbacks: list[Callable] = []
        self._timeout_callbacks: list[Callable] = []

        # 超时调度器
        self._timeout_scheduler: GatingTimeoutScheduler = GatingTimeoutScheduler(
            timeout_seconds=timeout_seconds,
        )

        # 注册超时回调到调度器
        self._timeout_scheduler.set_timeout_callback(self._on_timeout)

    # ============================================================
    # 回调注册
    # ============================================================

    def set_approve_callback(
        self, callback: Callable[[str, str, str], None]
    ) -> None:
        """注册审批成功回调。

        做什么：当用户批准工具调用时，触发此回调通知调用方（DAG 引擎）。
        输入：callback - 回调函数，签名 (audit_log_id, tool_id, task_id)。
        """
        self._approve_callbacks.append(callback)

    def set_reject_callback(
        self, callback: Callable[[str, str, str, str], None]
    ) -> None:
        """注册拒绝回调。

        做什么：当用户拒绝工具调用时，触发此回调通知调用方（DAG 引擎）。
        输入：callback - 回调函数，签名 (audit_log_id, tool_id, task_id, user_feedback)。
        """
        self._reject_callbacks.append(callback)

    def set_timeout_callback(
        self, callback: Callable[[str, str, str, str], None]
    ) -> None:
        """注册超时回调。

        做什么：当审批请求超时被自动标记为 TIMEOUT 时，触发此回调。
        输入：callback - 回调函数，签名 (audit_log_id, tool_id, task_id, trace_id)。
        """
        self._timeout_callbacks.append(callback)

    # ============================================================
    # 审批请求创建（拦截核心）
    # ============================================================

    async def create_auth_request(
        self,
        tool_id: str,
        tool_name: str,
        risk_level: str,
        reason: str,
        arguments: dict[str, Any],
        trace_id: str,
        task_id: str,
        goal: str = "",
        skill_info: dict[str, Any] | None = None,
        agent_output: str = "",
    ) -> tuple[bool, AuthRequestPayload | None]:
        """创建审批请求（拦截核心入口）。

        做什么：MCP 执行网关检测到 L2/L3 高危工具时调用此方法。
                在数据库创建审计日志 → 写入 Redis 缓存 → 通过 SSE
                向前端推送 EVT_TOOL_AUTH_REQUIRED 事件。
        为什么这样做：审批请求必须经过"数据库落盘 → 缓存同步 → 前端推送"
                     三重确认，确保在任何环节异常时都能恢复。
        输入：工具调用的完整上下文信息。
        输出：(bool, AuthRequestPayload | None) - (是否成功, 审批请求载荷)。
        边界条件：
            - 同一 trace_id + tool_id 的请求不可重复创建（防重）。
            - arguments 必须如实记录，不可截断。
            - 即使 SSE 推送失败也认为创建成功（前端可通过状态同步重建队列）。
        异常行为：数据库写入失败时返回 (False, None)。
        """
        # 1. 生成审计日志 ID
        audit_log_id: str = generate_string_id()
        now_ms: int = int(time.time() * 1000)

        # 2. 写入 PostgreSQL 审计日志
        create_success = await self._audit_repo.create(
            audit_log_id=audit_log_id,
            tool_id=tool_id,
            tool_name=tool_name,
            risk_level=risk_level,
            reason=reason,
            arguments=arguments,
            trace_id=trace_id,
            task_id=task_id,
            goal=goal,
            agent_output=agent_output,
        )

        if not create_success:
            logger.error(
                f"[GatingService] 创建审批请求失败（数据库写入异常）"
                f" tool={tool_name} risk={risk_level} trace_id={trace_id}"
            )
            return False, None

        # 3. 构建审批请求载荷
        auth_request = AuthRequestPayload(
            audit_log_id=audit_log_id,
            tool_id=tool_id,
            tool_name=tool_name,
            risk_level=risk_level,
            reason=reason,
            arguments=arguments,
            goal=goal,
            skill_info=skill_info,
            agent_output=agent_output,
            trace_id=trace_id,
            task_id=task_id,
            timestamp=now_ms,
            status=AuthStatus.PENDING,
            created_at=now_ms,
            updated_at=now_ms,
        )

        # 4. 写入 Redis 缓存（用于快速查询和状态同步）
        await self._cache_pending_request(auth_request)

        # 5. 通过 SSE 向前端推送 EVT_TOOL_AUTH_REQUIRED 事件
        await self._push_auth_required(auth_request)

        logger.info(
            f"[GatingService] 创建审批请求成功"
            f" audit_log_id={audit_log_id} tool={tool_name}"
            f" risk={risk_level} trace_id={trace_id}"
        )

        return True, auth_request

    # ============================================================
    # 审批处理（用户响应）
    # ============================================================

    async def approve_request(
        self, response: AuthResponsePayload
    ) -> bool:
        """处理用户批准请求。

        做什么：用户点击"同意"后更新审计日志状态为 APPROVED，
                从 Redis 中移除请求，触发审批成功回调。
        输入：response - 前端发来的审批响应载荷。
        输出：bool - 处理成功返回 True，失败返回 False。
        边界条件：
            - 已 APPROVED/REJECTED/TIMEOUT 的请求不可重复批准（幂等）。
            - 回调失败不阻断主流程，但记录错误日志。
        异常行为：数据库更新失败时返回 False。
        """
        audit_log_id = response.audit_log_id
        trace_id = response.trace_id

        # 1. 更新 PG 审计日志状态为 APPROVED
        success = await self._audit_repo.update_status(
            audit_log_id=audit_log_id,
            new_status=AuthStatus.APPROVED,
            user_feedback=response.user_feedback,
        )

        if not success:
            logger.warning(
                f"[GatingService] 批准请求失败（状态非 PENDING 或记录不存在）"
                f" audit_log_id={audit_log_id}"
            )
            return False

        # 2. 从 Redis 缓存中移除
        await self._remove_cached_request(audit_log_id)

        # 3. 触发审批成功回调
        for callback in self._approve_callbacks:
            try:
                callback(audit_log_id, response.tool_id, response.task_id)
            except Exception as e:
                logger.error(
                    f"[GatingService] 审批成功回调异常 audit_log_id={audit_log_id} error={e}"
                )

        logger.info(
            f"[GatingService] 审批通过 audit_log_id={audit_log_id} trace_id={trace_id}"
        )
        return True

    async def reject_request(
        self, response: AuthResponsePayload
    ) -> bool:
        """处理用户拒绝请求。

        做什么：用户点击"拒绝"后更新审计日志状态为 REJECTED，
                从 Redis 中移除请求，触发拒绝回调。
        输入：response - 前端发来的审批响应载荷。
        输出：bool - 处理成功返回 True，失败返回 False。
        边界条件：
            - 已 APPROVED/REJECTED/TIMEOUT 的请求不可重复拒绝（幂等）。
            - 无论 user_feedback 是否为空，都会传递给回调。
        异常行为：数据库更新失败时返回 False。
        """
        audit_log_id = response.audit_log_id
        trace_id = response.trace_id

        # 1. 更新 PG 审计日志状态为 REJECTED
        success = await self._audit_repo.update_status(
            audit_log_id=audit_log_id,
            new_status=AuthStatus.REJECTED,
            user_feedback=response.user_feedback,
        )

        if not success:
            logger.warning(
                f"[GatingService] 拒绝请求失败（状态非 PENDING 或记录不存在）"
                f" audit_log_id={audit_log_id}"
            )
            return False

        # 2. 从 Redis 缓存中移除
        await self._remove_cached_request(audit_log_id)

        # 3. 触发拒绝回调
        for callback in self._reject_callbacks:
            try:
                callback(
                    audit_log_id,
                    response.tool_id,
                    response.task_id,
                    response.user_feedback,
                )
            except Exception as e:
                logger.error(
                    f"[GatingService] 拒绝回调异常 audit_log_id={audit_log_id} error={e}"
                )

        logger.info(
            f"[GatingService] 审批拒绝 audit_log_id={audit_log_id} trace_id={trace_id}"
        )
        return True

    # ============================================================
    # 超时处理
    # ============================================================

    def _on_timeout(
        self,
        audit_log_id: str,
        tool_id: str,
        task_id: str,
        trace_id: str,
    ) -> None:
        """超时内部回调。

        做什么：当 GatingTimeoutScheduler 检测到超时记录时调用此方法。
                触发所有已注册的超时回调。
        输入：审计记录 ID、工具 ID、任务 ID、追踪 ID。
        为什么这样做：将超时处理与调度器解耦，方便扩展。
        """
        logger.warning(
            f"[GatingService] 审批请求超时"
            f" audit_log_id={audit_log_id} tool={tool_id} task_id={task_id}"
        )

        for callback in self._timeout_callbacks:
            try:
                callback(audit_log_id, tool_id, task_id, trace_id)
            except Exception as e:
                logger.error(
                    f"[GatingService] 超时回调异常 audit_log_id={audit_log_id} error={e}"
                )

    async def _check_timeout_records(
        self, timeout_seconds: int
    ) -> list[dict]:
        """查询超时的 PENDING 记录。

        做什么：从数据库查询所有创建时间超过 timeout_seconds 的 PENDING 记录。
        输入：timeout_seconds - 超时阈值（秒）。
        输出：list[dict] - 超时记录列表。
        边界条件：最多返回 100 条，防止单次扫描耗时过长。
        """
        try:
            all_pending = await self._audit_repo.get_pending()
            now_ms = int(time.time() * 1000)
            timeout_records = []
            for record in all_pending:
                created_at = record.get("created_at")
                if created_at:
                    # created_at 是 datetime 对象，转换为毫秒时间戳
                    created_ms = int(created_at.timestamp() * 1000)
                    if now_ms - created_ms > timeout_seconds * 1000:
                        timeout_records.append(record)
            return timeout_records[:100]
        except Exception as e:
            logger.error(f"[GatingService] 查询超时记录失败 error={e}")
            return []

    async def _mark_timeout_record(self, audit_log_id: str) -> bool:
        """将单条审计记录标记为 TIMEOUT。

        输入：audit_log_id - 审计记录 ID。
        输出：bool - 标记成功返回 True。
        """
        success = await self._audit_repo.update_status(
            audit_log_id=audit_log_id,
            new_status=AuthStatus.TIMEOUT,
        )
        if success:
            await self._remove_cached_request(audit_log_id)
        return success

    # ============================================================
    # 状态同步（断线重连后使用）
    # ============================================================

    async def sync_init_state(self) -> SyncInitStatePayload:
        """同步当前所有 PENDING 状态审批请求。

        做什么：前端断线重连或应用重启后调用。查询数据库所有 PENDING 状态
                的审计记录，组装为 SyncInitStatePayload 返回。
                前端收到后将 clearAll() 然后重新入队（见前端方案文档 6.3 节）。
        为什么这样做：状态撕裂最彻底的解决方案。前端每次重连都从零重建队列，
                     不信任任何本地缓存的状态。
        输出：SyncInitStatePayload - 包含所有 PENDING 请求的快照。
        边界条件：
            - 只返回 status = 'PENDING' 的记录。
            - 如果当前无 PENDING 请求，pending_requests 为空列表。
        """
        records = await self._audit_repo.get_pending()
        pending_list: list[AuthRequestPayload] = []

        for record in records:
            try:
                created_at_val = record.get("created_at")
                created_ms = (
                    int(created_at_val.timestamp() * 1000)
                    if created_at_val
                    else 0
                )

                request = AuthRequestPayload(
                    audit_log_id=record["id"],
                    tool_id=record.get("tool_id", ""),
                    tool_name=record.get("tool_name", ""),
                    risk_level=record.get("risk_level", "L2"),
                    reason=record.get("reason", ""),
                    arguments=record.get("arguments", {}),
                    goal=record.get("goal", ""),
                    skill_info=record.get("skill_info"),
                    agent_output=record.get("agent_output", ""),
                    trace_id=record.get("trace_id", ""),
                    task_id=record.get("task_id", ""),
                    timestamp=created_ms,
                    status=AuthStatus.PENDING,
                    created_at=created_ms,
                    updated_at=created_ms,
                )
                pending_list.append(request)
            except Exception as e:
                logger.error(
                    f"[GatingService] 状态同步解析记录失败"
                    f" audit_log_id={record.get('id', 'unknown')} error={e}"
                )

        return SyncInitStatePayload(
            pending_requests=pending_list,
            sync_timestamp=int(time.time() * 1000),
        )

    async def get_pending_count(self) -> int:
        """获取当前 PENDING 状态请求数量。

        输出：int - PENDING 记录数量。
        """
        return await self._audit_repo.get_pending_count()

    # ============================================================
    # Redis 缓存操作
    # ============================================================

    async def _cache_pending_request(
        self, request: AuthRequestPayload
    ) -> None:
        """将审批请求写入 Redis 缓存。

        做什么：将审批请求同时写入 Redis Set（用于快速获取所有 PENDING ID）
                和 Hash（用于获取单条请求详情）。
        为什么这样做：Redis 缓存在状态同步和超时扫描时提供快速读取，
                     减少对 PostgreSQL 的查询压力。
        输入：request - 审批请求载荷。
        边界条件：
            - 如果 Redis 不可用，静默跳过（降级策略）。
            - audit_log_id 为 Set 中的唯一元素。
        """
        if not self._redis_client:
            return

        try:
            client = self._redis_client.get_client()
            redis_key = f"{REDIS_GATING_REQUEST_PREFIX}{request.audit_log_id}"

            # 写入 Hash 结构
            await client.hset(
                redis_key,
                mapping={
                    "audit_log_id": request.audit_log_id,
                    "tool_id": request.tool_id,
                    "tool_name": request.tool_name,
                    "risk_level": request.risk_level,
                    "reason": request.reason,
                    "arguments": json.dumps(request.arguments, ensure_ascii=False),
                    "goal": request.goal,
                    "agent_output": request.agent_output,
                    "trace_id": request.trace_id,
                    "task_id": request.task_id,
                    "timestamp": str(request.timestamp),
                    "status": AuthStatus.PENDING.value,
                },
            )
            # 设置 TTL（超时时间 + 60 秒额外缓冲，防止过早过期）
            await client.expire(redis_key, 360)  # 6 分钟（300 秒超时 + 60 秒缓冲）

            # 加入 PENDING 集合
            await client.sadd(REDIS_GATING_PENDING_KEY, request.audit_log_id)
            # 集合的 TTL 在单个元素过期时由下游处理

        except Exception as e:
            logger.warning(
                f"[GatingService] Redis 缓存写入失败（降级处理）"
                f" audit_log_id={request.audit_log_id} error={e}"
            )

    async def _remove_cached_request(self, audit_log_id: str) -> None:
        """从 Redis 缓存中移除审批请求。

        做什么：审批完成后清理 Redis 中的缓存数据。
        输入：audit_log_id - 要移除的审计记录 ID。
        边界条件：如果 Redis 不可用，静默跳过。
        """
        if not self._redis_client:
            return

        try:
            client = self._redis_client.get_client()
            await client.delete(f"{REDIS_GATING_REQUEST_PREFIX}{audit_log_id}")
            await client.srem(REDIS_GATING_PENDING_KEY, audit_log_id)
        except Exception as e:
            logger.warning(
                f"[GatingService] Redis 缓存移除失败 audit_log_id={audit_log_id} error={e}"
            )

    # ============================================================
    # SSE 事件推送
    # ============================================================

    async def _push_auth_required(
        self, request: AuthRequestPayload
    ) -> None:
        """通过 SSE 向前端推送 EVT_TOOL_AUTH_REQUIRED 事件。

        做什么：创建审批请求后立即向前端推送事件，触发前端 Gating 弹窗。
        为什么这样做：前端不轮询审批状态，完全由后端主动推送驱动。
        输入：request - 完整的审批请求载荷。
        边界条件：
            - 如果 SSE 管理器不可用，静默跳过。
            - 推送失败不阻断主流程（前端可通过状态同步重建）。
        """
        if not self._sse_manager:
            return

        try:
            event_data = {
                "type": GatingEventType.EVT_TOOL_AUTH_REQUIRED.value,
                "schema_version": "1.0",
                "trace_id": request.trace_id,
                "task_id": request.task_id,
                "timestamp": request.timestamp,
                "payload": request.model_dump(mode="json"),
            }
            await self._sse_manager.publish(event_data)
            logger.info(
                f"[GatingService] SSE 推送 EVT_TOOL_AUTH_REQUIRED 成功"
                f" audit_log_id={request.audit_log_id}"
            )
        except Exception as e:
            logger.warning(
                f"[GatingService] SSE 推送 EVT_TOOL_AUTH_REQUIRED 失败"
                f" audit_log_id={request.audit_log_id} error={e}"
            )

    async def push_sync_state(self, sync_payload: SyncInitStatePayload) -> None:
        """向前端推送当前审批状态快照。

        做什么：当后端内部状态变化（如超时清理）或前端明确请求状态同步时，
                将当前所有 PENDING 审批请求推送给前端。
        输入：sync_payload - 状态同步载荷。
        边界条件：推送失败不阻断主流程。
        """
        if not self._sse_manager:
            return

        try:
            event_data = {
                "type": GatingEventType.EVT_INIT_STATE.value,
                "schema_version": "1.0",
                "trace_id": "gating_sync",
                "timestamp": sync_payload.sync_timestamp,
                "payload": sync_payload.model_dump(mode="json"),
            }
            await self._sse_manager.publish(event_data)
        except Exception as e:
            logger.error(f"[GatingService] SSE 推送状态同步失败 error={e}")

    # ============================================================
    # 调度器生命周期管理
    # ============================================================

    async def start_timeout_scheduler(self) -> None:
        """启动后台超时检测调度器。

        做什么：启动 GatingTimeoutScheduler，开始定期扫描超时请求。
        为什么这样做：应用启动时调用，确保超时机制始终运行。
        """
        await self._timeout_scheduler.start(
            check_timeout_func=self._check_timeout_records,
            mark_timeout_func=self._mark_timeout_record,
        )

    async def stop_timeout_scheduler(self) -> None:
        """停止后台超时检测调度器。

        做什么：应用关闭时调用，清理后台协程。
        """
        await self._timeout_scheduler.stop()
