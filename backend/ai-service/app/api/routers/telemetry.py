"""
Luna AI 可观测性路由。

做什么：处理链路、审计、监控指标以及上下文压缩回放查询请求。
为什么这样做：前端调试面板需要通过稳定的 HTTP 接口读取链路详情、原始审计日志和压缩回放结构。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from app.context.compression_replay import (
    build_compression_audit_list_payload,
    build_compression_replay_response,
    parse_compression_audit_payload,
)
from app.logger import logger
from app.types.constants import COMPRESSION_AUDIT_ACTION_TYPE, COMPRESSION_SPAN_NAME
from app.types.errors import ErrorCode, ResponseModel, create_error_response, create_success_response
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


def get_db_session(request: Request):
    """从 `app.state` 获取 PostgreSQL 会话工厂。"""
    return request.app.state.pg_client.get_session()


async def _query_trace_spans(
    request: Request,
    *,
    trace_id: Optional[str] = None,
    span_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """
    查询 Span 列表。

    做什么：复用统一查询逻辑读取链路追踪 Span。
    为什么这样做：普通链路查询与压缩回放查询都需要访问 `trace_spans`。
    输入输出：输入 trace_id、span_name、分页参数，输出 (total, spans)。
    边界条件：span_name 为空时不过滤名称。
    异常行为：数据库异常向上抛出，由路由层统一返回错误响应。
    """
    from sqlalchemy import func, select

    from app.telemetry.worker import TraceSpan

    async for session in get_db_session(request):
        stmt = select(TraceSpan)
        if trace_id:
            stmt = stmt.where(TraceSpan.trace_id == trace_id)
        if span_name:
            stmt = stmt.where(TraceSpan.name == span_name)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.order_by(TraceSpan.start_time.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        spans_orm = result.scalars().all()
        spans = [
            {
                "id": span.id,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "name": span.name,
                "service": span.service,
                "start_time": span.start_time.isoformat() if span.start_time else None,
                "end_time": span.end_time.isoformat() if span.end_time else None,
                "duration_ms": span.duration_ms,
                "status": span.status,
                "attributes": span.attributes,
            }
            for span in spans_orm
        ]
        return total, spans
    return 0, []


async def _query_audit_logs(
    request: Request,
    *,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list]:
    """
    查询审计日志 ORM 列表。

    做什么：统一读取 `audit_logs` 表中的审计记录。
    为什么这样做：原始审计日志、压缩审计列表和压缩回放详情都会复用同一查询入口。
    输入输出：输入过滤条件与分页参数，输出 (total, logs_orm)。
    边界条件：不传过滤条件时按时间倒序返回所有审计日志。
    异常行为：数据库异常向上抛出，由路由层统一处理。
    """
    from sqlalchemy import func, select

    from app.telemetry.worker import AuditLog

    async for session in get_db_session(request):
        stmt = select(AuditLog)
        if action_type:
            stmt = stmt.where(AuditLog.action_type == action_type)
        if status:
            stmt = stmt.where(AuditLog.status == status)
        if trace_id:
            stmt = stmt.where(AuditLog.trace_id == trace_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return total, result.scalars().all()
    return 0, []


@router.get("/traces", response_model=ResponseModel)
async def get_traces(
    request: Request,
    trace_id: Optional[str] = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> ResponseModel:
    """获取链路详情。"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    try:
        total, spans = await _query_trace_spans(
            request,
            trace_id=trace_id,
            limit=limit,
            offset=offset,
        )
        return create_success_response({"total": total, "spans": spans}, req_trace_id)
    except Exception as exc:
        logger.error(f"获取链路详情失败 error={exc}")
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取链路详情失败", req_trace_id)


@router.get("/audit_logs", response_model=ResponseModel)
async def get_audit_logs(
    request: Request,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> ResponseModel:
    """查询原始审计日志。"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    try:
        total, logs_orm = await _query_audit_logs(
            request,
            action_type=action_type,
            status=status,
            trace_id=trace_id,
            limit=limit,
            offset=offset,
        )
        logs = [
            {
                "id": log.id,
                "trace_id": log.trace_id,
                "action_type": log.action_type,
                "status": log.status,
                "details": log.details,
                "error_msg": log.error_msg,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs_orm
        ]
        return create_success_response({"total": total, "logs": logs}, req_trace_id)
    except Exception as exc:
        logger.error(f"获取审计日志失败 error={exc}")
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取审计日志失败", req_trace_id)


@router.get("/compression_audits", response_model=ResponseModel)
async def get_compression_audits(
    request: Request,
    status: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> ResponseModel:
    """
    查询上下文压缩审计列表。

    做什么：读取 `CONTEXT_COMPRESSION` 审计记录，并把 details 解析为结构化压缩审计载荷。
    为什么这样做：前端需要直接消费后端整理好的压缩审计结构，而不是自行解析 JSON。
    输入输出：支持按 `status`、`trace_id` 和分页参数查询。
    边界条件：details 无法解析为压缩载荷时自动跳过该条记录。
    异常行为：数据库查询失败时返回统一错误响应。
    """
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    try:
        total, logs_orm = await _query_audit_logs(
            request,
            action_type=COMPRESSION_AUDIT_ACTION_TYPE,
            status=status,
            trace_id=trace_id,
            limit=limit,
            offset=offset,
        )
        payloads = []
        for log in logs_orm:
            payload = parse_compression_audit_payload(log.details)
            if payload is not None:
                payloads.append(payload)
        return create_success_response(
            build_compression_audit_list_payload(payloads, total=total),
            req_trace_id,
        )
    except Exception as exc:
        logger.error(f"获取压缩审计列表失败 error={exc}")
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取压缩审计列表失败", req_trace_id)


@router.get("/compression_replays/{trace_id}", response_model=ResponseModel)
async def get_compression_replay(
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """
    查询指定 `trace_id` 的上下文压缩回放详情。

    做什么：聚合同一链路下的压缩审计动作和压缩 Span，返回总览、事件时间线和快照列表。
    为什么这样做：前端调试页应直接获得完整回放结构，而不是自己拼接多张表的结果。
    输入输出：输入 `trace_id`，输出 `CompressionReplayResponse` 对应的 data 结构。
    边界条件：查不到任何压缩审计时返回空事件列表和空摘要。
    异常行为：数据库或 JSON 解析失败时返回统一错误响应。
    """
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    try:
        _, logs_orm = await _query_audit_logs(
            request,
            action_type=COMPRESSION_AUDIT_ACTION_TYPE,
            trace_id=trace_id,
            limit=500,
            offset=0,
        )
        payloads = []
        for log in logs_orm:
            payload = parse_compression_audit_payload(log.details)
            if payload is not None:
                payloads.append(payload)
        _, spans = await _query_trace_spans(
            request,
            trace_id=trace_id,
            span_name=COMPRESSION_SPAN_NAME,
            limit=500,
            offset=0,
        )
        replay_response = build_compression_replay_response(payloads, spans)
        if not replay_response.trace_id:
            replay_response.trace_id = trace_id
        return create_success_response(replay_response.model_dump(mode="json"), req_trace_id)
    except Exception as exc:
        logger.error(f"获取压缩回放详情失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取压缩回放详情失败", req_trace_id)


@router.get("/metrics", response_model=ResponseModel)
async def get_metrics(
    request: Request,
    range: str = Query("1h"),
) -> ResponseModel:
    """获取实时监控指标。"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    try:
        from app.telemetry.metrics import get_metrics_buffer

        buffer = get_metrics_buffer()
        if not buffer:
            return create_error_response(ErrorCode.SYSTEM_ERROR, "Metrics buffer not initialized", req_trace_id)

        n = 60
        if range == "24h":
            n = 1440
        points = buffer.get_recent(n)
        return create_success_response(points, req_trace_id)
    except Exception as exc:
        logger.error(f"获取监控指标失败 error={exc}")
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取监控指标失败", req_trace_id)
