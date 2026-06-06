"""
Luna AI 可观测性后台 Worker

做什么：负责消费队列中的 Span 和 Audit 事件，批量写入 PostgreSQL。
为什么这样做：异步记录遥测数据，避免阻塞主业务流程。
输入输出：
    - Worker: 遥测后台 Worker 类
边界条件：
    - 队列满时丢弃数据并记录警告
    - 定时或达到批处理大小时刷新数据到数据库
异常行为：
    - 写入数据库失败时记录错误并降级（打印日志）
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.infrastructure.postgres import PostgresClient
from app.logger import logger


class Base(DeclarativeBase):
    """
    遥测模块独立声明式基类。

    做什么：承载 trace_spans 与 audit_logs 两张可观测性表的 SQLAlchemy 元数据。
    为什么这样做：遥测 Worker 可独立批量写入，不与业务模型注册流程互相污染。
    输入输出：无业务输入输出，供本模块 ORM 模型继承。
    边界条件：不直接创建表字段。
    异常行为：子类映射异常由 SQLAlchemy 抛出。
    """


class TraceSpan(Base):
    """链路追踪 Span 模型"""
    __tablename__ = "trace_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    span_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    service: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50))
    attributes: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    """审计日志模型"""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    details: Mapped[str] = mapped_column(Text)
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Worker:
    """可观测性后台 Worker"""

    def __init__(self, pg_client: PostgresClient, batch_size: int = 100, flush_interval_sec: float = 0.5):
        self.pg_client = pg_client
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        
        # 使用 asyncio.Queue 替代 Go 的 chan
        self.span_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=10000)
        self.audit_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=10000)
        
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def record_span_async(self, span: Dict[str, Any]) -> None:
        """异步记录 Span"""
        try:
            self.span_queue.put_nowait(span)
        except asyncio.QueueFull:
            logger.warning(f"Telemetry span queue full, dropping span span_id={span.get('span_id')}")

    def record_audit_log_async(self, audit: Dict[str, Any]) -> None:
        """异步记录审计日志"""
        try:
            self.audit_queue.put_nowait(audit)
        except asyncio.QueueFull:
            logger.warning(f"Telemetry audit queue full, dropping audit log audit_id={audit.get('id')}")

    async def update_audit_log_async(self, id: str, status: str, err_msg: str) -> None:
        """异步更新审计日志状态"""
        # 为了简单起见，这里直接异步执行更新，不走 batch
        try:
            async for session in self.pg_client.get_session():
                from sqlalchemy import update
                stmt = (
                    update(AuditLog)
                    .where(AuditLog.id == id)
                    .values(status=status, error_msg=err_msg)
                )
                await session.execute(stmt)
                await session.commit()
                return
        except Exception as e:
            logger.error(f"Failed to update audit log audit_id={id} error={e}")

    async def start(self) -> None:
        """启动 Worker 主循环"""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Telemetry worker started")

    async def stop(self) -> None:
        """停止 Worker 并刷新剩余数据"""
        if not self._running:
            return
            
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("遥测 Worker 主任务已按关闭流程取消")
                
        # 刷新剩余数据
        await self._flush_remaining()
        logger.info("Telemetry worker stopped")

    async def _run_loop(self) -> None:
        """Worker 主循环"""
        span_batch: List[Dict[str, Any]] = []
        audit_batch: List[Dict[str, Any]] = []
        
        while self._running:
            try:
                # 使用 wait_for 实现类似 Go 的 select + ticker
                # 等待队列中有数据，或者超时触发刷新
                
                # 尝试获取 span
                try:
                    span = await asyncio.wait_for(self.span_queue.get(), timeout=self.flush_interval_sec)
                    span_batch.append(span)
                    self.span_queue.task_done()
                    
                    if len(span_batch) >= self.batch_size:
                        await self._flush_spans(span_batch)
                        span_batch = []
                except asyncio.TimeoutError:
                    # 超时，触发刷新
                    if span_batch:
                        await self._flush_spans(span_batch)
                        span_batch = []
                        
                # 尝试获取 audit (非阻塞)
                while not self.audit_queue.empty() and len(audit_batch) < self.batch_size:
                    audit = self.audit_queue.get_nowait()
                    audit_batch.append(audit)
                    self.audit_queue.task_done()
                    
                if len(audit_batch) >= self.batch_size or (audit_batch and not span_batch):
                    await self._flush_audit_logs(audit_batch)
                    audit_batch = []
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telemetry worker loop error: {e}")
                await asyncio.sleep(1) # 避免错误导致死循环消耗 CPU

    async def _flush_remaining(self) -> None:
        """刷新队列中剩余的所有数据"""
        span_batch = []
        while not self.span_queue.empty():
            span_batch.append(self.span_queue.get_nowait())
            self.span_queue.task_done()
            
        if span_batch:
            await self._flush_spans(span_batch)
            
        audit_batch = []
        while not self.audit_queue.empty():
            audit_batch.append(self.audit_queue.get_nowait())
            self.audit_queue.task_done()
            
        if audit_batch:
            await self._flush_audit_logs(audit_batch)

    async def _flush_spans(self, batch: List[Dict[str, Any]]) -> None:
        """批量写入 Spans"""
        if not batch:
            return
            
        try:
            async for session in self.pg_client.get_session():
                # 转换为 ORM 模型
                models = []
                for s in batch:
                    models.append(TraceSpan(
                        trace_id=s.get("trace_id", ""),
                        span_id=s.get("span_id", ""),
                        name=s.get("name", ""),
                        service=s.get("service", ""),
                        start_time=s.get("start_time"),
                        end_time=s.get("end_time"),
                        duration_ms=s.get("duration_ms", 0),
                        status=s.get("status", ""),
                        attributes=s.get("attributes", "{}"),
                    ))
                
                session.add_all(models)
                await session.commit()
                return
        except Exception as e:
            logger.error(f"Failed to flush trace spans error={e} count={len(batch)}")
            self._fallback_log("span", batch)

    async def _flush_audit_logs(self, batch: List[Dict[str, Any]]) -> None:
        """批量写入审计日志"""
        if not batch:
            return
            
        try:
            async for session in self.pg_client.get_session():
                # 转换为 ORM 模型
                models = []
                for a in batch:
                    models.append(AuditLog(
                        id=a.get("id", ""),
                        trace_id=a.get("trace_id", ""),
                        action_type=a.get("action_type", ""),
                        status=a.get("status", ""),
                        details=a.get("details", ""),
                        error_msg=a.get("error_msg"),
                        timestamp=a.get("timestamp"),
                    ))
                
                session.add_all(models)
                await session.commit()
                return
        except Exception as e:
            logger.error(f"Failed to flush audit logs error={e} count={len(batch)}")
            self._fallback_log("audit", batch)

    def _fallback_log(self, typ: str, batch: List[Dict[str, Any]]) -> None:
        """降级：写入失败时转写本地应急文件 (这里简化处理，仅打印日志)"""
        try:
            # 处理 datetime 序列化
            def default_serializer(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Type {type(obj)} not serializable")
                
            data = json.dumps(batch, default=default_serializer)
            logger.error(f"FALLBACK_LOG type={typ} data={data}")
        except Exception as e:
            logger.error(f"Failed to write fallback log: {e}")


# 全局单例
_global_worker: Optional[Worker] = None

def init_worker(pg_client: PostgresClient) -> None:
    """初始化全局 Worker"""
    global _global_worker
    _global_worker = Worker(pg_client, batch_size=100, flush_interval_sec=0.5)

def get_worker() -> Optional[Worker]:
    """获取全局 Worker"""
    return _global_worker
