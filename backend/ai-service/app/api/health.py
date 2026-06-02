from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.types.errors import ResponseModel, create_success_response

router = APIRouter()

@router.get("/health", response_model=ResponseModel)
async def health_check(request: Request) -> ResponseModel:
    """健康检查接口"""
    trace_id = request.headers.get("X-Trace-ID", "")
    
    data = {
        "status": "ok",
        "service": "luna-ai-service",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return create_success_response(data, trace_id)
