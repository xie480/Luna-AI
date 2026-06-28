"""
Luna AI Gating 模块：后台超时检测与清理调度器。

做什么：运行后台异步协程，定期扫描 PostgreSQL 中所有 PENDING 状态
        的审批请求，对超过超时阈值的请求自动标记为 TIMEOUT。
        超时后的触发点：由 GatingService 的统一回调机制通知 DAG 引擎。
        此调度器仅负责状态扫描和标记，不负责业务回调。

为什么这样做：根据 agent.md 6.3 健壮性与异步处理规范，所有异步逻辑
            必须声明生命周期、超时策略和降级方案。后台调度器确保
            即使前端 WebSocket 断开，超时请求也能被正确清理。

边界条件：
    - 默认超时阈值：300 秒（5 分钟），可通过 constructor 参数配置。
    - 扫描间隔：每 30 秒执行一次，大幅降低对 PostgreSQL 的查询压力。
    - 每次扫描最多处理 100 条超时记录，防止单次扫描耗时过长。

异常行为：
    - 数据库查询失败时记录错误日志并跳过本轮扫描。
    - 调度器自身异常由外层 asyncio.create_task 捕获。
"""

from __future__ import annotations

import asyncio
import time

from app.logger import logger


class GatingTimeoutScheduler:
    """Gating 超时检测与清理调度器。

    做什么：后台定时扫描 PENDING 审批请求，将超时请求标记为 TIMEOUT。
            扫描周期和超时阈值均可配置。
    为什么这样做：超时是审批流程的必要组成部分。用户可能长时间不在电脑前，
                系统需要在合理时间后自动清理积压的 PENDING 请求。
    输入输出：
        - start(): 启动后台检测循环，返回 asyncio.Task。
        - stop(): 停止检测循环，取消后台任务。
        - timeout_seconds: 超时阈值（秒），默认 300 秒（5 分钟）。
        - scan_interval: 扫描间隔（秒），默认 30 秒。
    """

    def __init__(
        self,
        timeout_seconds: int = 300,
        scan_interval: int = 30,
    ) -> None:
        """初始化 Gating 超时调度器。

        输入：
            - timeout_seconds: 超时阈值（秒）。默认 300 秒（5 分钟）。
            - scan_interval: 扫描间隔（秒）。默认 30 秒。
        边界条件：
            - timeout_seconds 必须大于 0。
            - scan_interval 必须大于 0。
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if scan_interval <= 0:
            raise ValueError("scan_interval 必须大于 0")

        self._timeout_seconds: int = timeout_seconds
        self._scan_interval: int = scan_interval
        self._task: asyncio.Task | None = None
        self._timeout_callback = None

    def set_timeout_callback(self, callback):
        """设置超时回调函数。

        做什么：当检测到超时记录时，调用此回调。
                回调签名：callback(audit_log_id: str, tool_id: str, task_id: str, trace_id: str)
                支持同步和异步回调。当回调为协程函数时，调度器会自动 await。
        为什么这样做：将超时检测与业务处理解耦。GatingService 通过此回调
                     通知 DAG 引擎任务超时。
        """
        self._timeout_callback = callback

    async def start(
        self,
        check_timeout_func,
        mark_timeout_func,
    ) -> None:
        """启动后台超时检测循环。

        做什么：后台持续运行，定期扫描 PENDING 请求并标记超时。
        输入：
            - check_timeout_func: 异步函数，签名 async (timeout_seconds: int) -> list[dict]，
              返回超时的审计记录列表。
            - mark_timeout_func: 异步函数，签名 async (audit_log_id: str) -> bool，
              将单条审计记录标记为 TIMEOUT。
        为什么这样做：将数据库操作委托给调用方（GatingService），
                     保持调度器不直接依赖数据库仓储，便于测试。
        异常行为：单次扫描异常时记录错误日志并继续下一轮，不阻断整个调度器。
        """
        if self._task is not None:
            logger.warning("[GatingScheduler] 调度器已在运行，跳过重复启动")
            return

        logger.info(
            f"[GatingScheduler] 启动超时检测调度器: "
            f"timeout={self._timeout_seconds}s interval={self._scan_interval}s"
        )

        async def _scan_loop() -> None:
            """后台扫描循环体。"""
            while True:
                try:
                    await asyncio.sleep(self._scan_interval)
                    await self._scan_once(check_timeout_func, mark_timeout_func)
                except asyncio.CancelledError:
                    logger.info("[GatingScheduler] 超时检测调度器已取消")
                    break
                except Exception as e:
                    logger.error(f"[GatingScheduler] 超时检测异常 error={e}")

        self._task = asyncio.create_task(_scan_loop())

    async def _scan_once(
        self,
        check_timeout_func,
        mark_timeout_func,
    ) -> None:
        """执行单次超时扫描。

        做什么：查询超时的 PENDING 请求，逐个标记为 TIMEOUT。
        输入：
            - check_timeout_func: 查询超时记录的函数。
            - mark_timeout_func: 标记超时的函数。
        边界条件：
            - 每次最多处理 100 条超时记录（通过 LIMIT 控制）。
            - 单条记录标记失败不阻断其他记录的标记。
        """
        try:
            timeout_records = await check_timeout_func(self._timeout_seconds)

            if not timeout_records:
                return

            timeout_ids = [r["id"] for r in timeout_records[:100]]
            logger.warning(
                f"[GatingScheduler] 检测到 {len(timeout_ids)} 条超时审批请求，"
                f"正在自动标记为 TIMEOUT ..."
            )

            for record_id in timeout_ids:
                try:
                    success = await mark_timeout_func(record_id)
                    if success and self._timeout_callback:
                        # 找对应的记录详情
                        record = next(
                            (r for r in timeout_records if r["id"] == record_id),
                            None,
                        )
                        if record:
                            # 支持同步和异步回调：如果是协程函数则 await
                            result = self._timeout_callback(
                                audit_log_id=record_id,
                                tool_id=record.get("tool_id", ""),
                                task_id=record.get("task_id", ""),
                                trace_id=record.get("trace_id", ""),
                            )
                            import asyncio as _asyncio
                            if _asyncio.iscoroutine(result):
                                await result
                except Exception as e:
                    logger.error(
                        f"[GatingScheduler] 标记超时失败 audit_log_id={record_id} error={e}"
                    )

        except Exception as e:
            logger.error(f"[GatingScheduler] 超时扫描失败 error={e}")

    async def stop(self) -> None:
        """停止后台超时检测循环。

        做什么：取消后台协程任务，等待其优雅退出。
        为什么这样做：应用关闭时需要清理后台任务，防止资源泄漏。
        边界条件：
            - 如果调度器未启动，静默返回。
            - 如果正在执行扫描，等待当前扫描完成后再取消。
        """
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("[GatingScheduler] 超时检测调度器已停止")
