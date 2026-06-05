from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.types.errors import ResponseModel, create_success_response

router = APIRouter()

@router.get("/health", response_model=ResponseModel)
async def health_check(request: Request) -> ResponseModel:
    """健康检查接口"""
    trace_id = request.headers.get("X-Trace-ID", "")
    
    is_ready = getattr(request.app.state, "is_ready", False)
    
    data = {
        "status": "ready" if is_ready else "starting",
        "service": "luna-ai-service",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return create_success_response(data, trace_id)


@router.get("/ready", response_model=ResponseModel)
async def ready_check(request: Request) -> ResponseModel:
    """
    服务就绪检查端点（专供加载动画使用）。

    做什么：只有后端完成所有核心资源初始化（即 lifespan 执行完毕，is_ready=True）时
            才返回 status="ready"。该端点只有在 lifespan yield 之后才能被外部访问，
            因此能够确保 "Luna AI Service 所有核心资源初始化完成" 和
            "Application startup complete." 两条日志已输出。
    为什么这样做：与 /health 通用健康检查分离，前端加载动画专门依赖此端点判断
            服务是否完全就绪，避免被 SSE 连接事件中的 is_ready 标志提前触发。
    """
    trace_id = request.headers.get("X-Trace-ID", "")
    
    is_ready = getattr(request.app.state, "is_ready", False)
    
    if not is_ready:
        return create_success_response({"status": "starting"}, trace_id)
    
    return create_success_response({
        "status": "ready",
        "service": "luna-ai-service",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }, trace_id)
