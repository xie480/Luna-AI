"""
Luna AI 可观测性路由

做什么：处理可观测性相关的 HTTP 请求。
为什么这样做：提供前端查询链路详情、审计日志和实时监控指标的接口。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from app.logger import logger
from app.types.errors import ResponseModel, create_error_response, create_success_response
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


# 依赖注入占位符，实际应用中应在 main.py 中覆盖或通过 Request.app.state 获取
# 这里简化处理，因为 Python 端目前没有完整的 telemetry worker 实现
# 实际的 telemetry 数据可能存储在 PostgreSQL 中
def get_db_session(request: Request):
    return request.app.state.pg_client.get_session()


@router.get("/traces", response_model=ResponseModel)
async def get_traces(
    request: Request,
    trace_id: Optional[str] = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> ResponseModel:
    """获取链路详情"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        from sqlalchemy import select, func
        from app.telemetry.worker import TraceSpan
        
        async for session in get_db_session(request):
            stmt = select(TraceSpan)
            if trace_id:
                stmt = stmt.where(TraceSpan.trace_id == trace_id)
                
            # Count total
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total_result = await session.execute(count_stmt)
            total = total_result.scalar_one()
            
            # Get paginated results
            stmt = stmt.order_by(TraceSpan.start_time.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            spans_orm = result.scalars().all()
            
            spans = []
            for s in spans_orm:
                spans.append({
                    "id": s.id,
                    "trace_id": s.trace_id,
                    "span_id": s.span_id,
                    "name": s.name,
                    "service": s.service,
                    "start_time": s.start_time.isoformat() if s.start_time else None,
                    "end_time": s.end_time.isoformat() if s.end_time else None,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "attributes": s.attributes,
                })
            break
        
        return create_success_response({
            "total": total,
            "spans": spans,
        }, req_trace_id)
    except Exception as e:
        logger.error(f"获取链路详情失败 error={e}")
        from app.types.errors import ErrorCode
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
    """查询审计日志"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        from sqlalchemy import select, func
        from app.telemetry.worker import AuditLog
        
        async for session in get_db_session(request):
            stmt = select(AuditLog)
            if action_type:
                stmt = stmt.where(AuditLog.action_type == action_type)
            if status:
                stmt = stmt.where(AuditLog.status == status)
            if trace_id:
                stmt = stmt.where(AuditLog.trace_id == trace_id)
                
            # Count total
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total_result = await session.execute(count_stmt)
            total = total_result.scalar_one()
            
            # Get paginated results
            stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            logs_orm = result.scalars().all()
            
            logs = []
            for l in logs_orm:
                logs.append({
                    "id": l.id,
                    "trace_id": l.trace_id,
                    "action_type": l.action_type,
                    "status": l.status,
                    "details": l.details,
                    "error_msg": l.error_msg,
                    "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                })
            break
        
        return create_success_response({
            "total": total,
            "logs": logs,
        }, req_trace_id)
    except Exception as e:
        logger.error(f"获取审计日志失败 error={e}")
        from app.types.errors import ErrorCode
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取审计日志失败", req_trace_id)


@router.get("/metrics", response_model=ResponseModel)
async def get_metrics(
    request: Request,
    range: str = Query("1h"),
) -> ResponseModel:
    """获取实时监控指标"""
    req_trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        # 简化实现：返回空列表
        points = []
        
        return create_success_response(points, req_trace_id)
    except Exception as e:
        logger.error(f"获取监控指标失败 error={e}")
        from app.types.errors import ErrorCode
        return create_error_response(ErrorCode.SYSTEM_ERROR, "获取监控指标失败", req_trace_id)
