"""
Luna AI Gating 权限治理 API 路由模块。

做什么：提供 Phase 13 权限治理与前端 Gating 的 HTTP API 端点。
        前端通过 SSE 接收 EVT_TOOL_AUTH_REQUIRED 事件后，通过此模块
        发送 CMD_TOOL_AUTH_RESPONSE（审批/拒绝）或 CMD_SYNC_GATING_STATE（状态同步）。

为什么这样做：根据 frontend/docs/plans/phase13_frontend_gating_plan.md 中的接口规约，
             前端通过标准 HTTP POST 提交用户审批结果，后端同步更新数据库并触发 DAG 回调。

API 端点：
    POST /api/gating/auth_response    — 处理用户审批响应（APPROVE / REJECT）
    POST /api/gating/sync_init_state  — 同步当前所有 PENDING 状态审批请求
    GET  /api/gating/pending_count    — 获取当前 PENDING 请求数量（用于调试面板）

边界条件：
    - 所有端点必须携带 X-Trace-ID 请求头（自动生成或透传）。
    - 请求体使用 Pydantic 模型严格校验。
    - 审批响应中的 audit_log_id 必须对应一个存在的 PENDING 记录。

异常行为：
    - 参数校验失败返回 422。
    - 审批响应处理失败返回 400（如状态已变更）。
    - 服务未初始化返回 503。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.gating.service import GatingService
from app.gating.types import AuthAction, AuthResponsePayload
from app.logger import logger
from app.types.constants import (
    WS_MSG_TYPE_CMD_TOOL_AUTH_RESPONSE,
    WS_MSG_TYPE_EVT_GATING_STATE,
    WS_MSG_TYPE_CMD_SYNC_GATING_STATE,
)
from app.types.errors import (
    ErrorCode,
    ResponseModel,
    create_error_response,
    create_success_response,
)
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/gating", tags=["gating"])


# ============================================================
# Pydantic 请求模型
# ============================================================


class AuthResponseRequest(BaseModel):
    """用户审批响应请求体。

    做什么：前端在用户点击"同意/拒绝"后发送的 HTTP 请求体。
    为什么这样做：使用 Pydantic 模型确保请求参数的类型安全和枚举约束。
                  Phase 13 新增 session_id 字段用于审批结果持久化。
    """
    audit_log_id: str = Field(
        ..., min_length=1, description="审计日志记录 ID。"
    )
    action: AuthAction = Field(
        ..., description="审批行为：APPROVE（同意）或 REJECT（拒绝）。"
    )
    user_feedback: str = Field(
        default="", max_length=2000,
        description="用户反馈理由或修改意见（可选）。",
    )
    tool_id: str = Field(
        default="", description="工具唯一标识。"
    )
    task_id: str = Field(
        default="", description="关联的 DAG 任务 ID。"
    )
    session_id: str = Field(
        default="", description="关联的会话 ID。用于审批结果持久化到 Redis"
                    "时的 Key 组织，供下一次工作流执行时消费。",
    )


class SyncInitStateRequest(BaseModel):
    """状态同步初始化请求体。

    做什么：前端断线重连后发送状态同步请求。
    为什么这样做：允许前端在需要时主动触发状态同步。
    """
    force: bool = Field(
        default=False,
        description="是否强制刷新。True 表示前端已 clearAll()，需要完整重建。",
    )


# ============================================================
# 依赖注入
# ============================================================


async def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """从请求头获取 trace_id，若不存在则自动生成。"""
    return x_trace_id or generate_string_id()


async def get_gating_service(request: Request) -> GatingService:
    """从 app.state 获取 GatingService 实例。

    做什么：FastAPI 依赖注入函数，从应用状态中获取 GatingService。
    为什么这样做：避免在每个路由中重复提取 app.state 的逻辑。
    异常行为：服务未初始化时抛出 503 异常。
    """
    gating_service: Optional[GatingService] = getattr(
        request.app.state, "gating_service", None
    )
    if gating_service is None:
        raise HTTPException(
            status_code=503,
            detail="GatingService 未初始化",
        )
    return gating_service


# ============================================================
# API 端点
# ============================================================


@router.post("/auth_response", response_model=ResponseModel)
async def handle_auth_response(
    request_body: AuthResponseRequest,
    trace_id: str = Depends(get_trace_id),
    gating_service: GatingService = Depends(get_gating_service),
) -> ResponseModel:
    """处理用户审批响应（APPROVE / REJECT）。

    做什么：接收前端发来的用户审批结果，更新审计日志状态并触发 DAG 回调。
    输入：request_body - 包含 audit_log_id、action、user_feedback 等。
    输出：ResponseModel - 标准响应模型。
    边界条件：
        - action 只能是 APPROVE 或 REJECT。
        - audit_log_id 必须存在且处于 PENDING 状态。
        - 重复操作（已处理过的 audit_log_id）返回错误。
    异常行为：
        - audit_log_id 为空时返回 400。
        - 审批处理失败时返回 500。
    """
    logger.info(
        f"[GatingAPI] 收到审批响应 trace_id={trace_id} "
        f"audit_log_id={request_body.audit_log_id} "
        f"action={request_body.action.value}"
    )

    if not request_body.audit_log_id:
        return create_error_response(
            code=400,
            msg="audit_log_id 不能为空",
            trace_id=trace_id,
        )

    # 构建审批响应载荷
    response_payload = AuthResponsePayload(
        audit_log_id=request_body.audit_log_id,
        action=request_body.action,
        user_feedback=request_body.user_feedback,
        trace_id=trace_id,
        task_id=request_body.task_id,
        session_id=request_body.session_id,
    )

    # 根据 action 分发处理
    if request_body.action == AuthAction.APPROVE:
        success = await gating_service.approve_request(response_payload)
    elif request_body.action == AuthAction.REJECT:
        success = await gating_service.reject_request(response_payload)
    else:
        return create_error_response(
            code=400,
            msg=f"非法的审批行为: {request_body.action}",
            trace_id=trace_id,
        )

    if not success:
        return create_error_response(
            code=ErrorCode.STATE_INVALID.value,
            msg="审批请求处理失败（可能已过期或状态已变更）",
            trace_id=trace_id,
        )

    return create_success_response(
        data={
            "audit_log_id": request_body.audit_log_id,
            "action": request_body.action.value,
            "message": "审批已确认" if request_body.action == AuthAction.APPROVE else "已拒绝执行",
        },
        trace_id=trace_id,
    )


@router.post("/sync_init_state", response_model=ResponseModel)
async def handle_sync_init_state(
    request_body: SyncInitStateRequest,
    trace_id: str = Depends(get_trace_id),
    gating_service: GatingService = Depends(get_gating_service),
) -> ResponseModel:
    """同步当前所有 PENDING 状态的审批请求。

    做什么：前端断线重连后调用此接口获取当前所有待处理的审批请求。
            前端收到响应后将执行 clearAll() 然后重新入队。
    为什么这样做：根据前端 Gating 方案文档 6.3 节，这是消除状态撕裂
                 最彻底的方案。前端不信任任何本地缓存的状态。
    输入：request_body - force 参数标记前端是否需要完整重建。
    输出：ResponseModel - 包含 pending_requests 列表的响应。
    """
    logger.info(f"[GatingAPI] 收到状态同步请求 trace_id={trace_id} force={request_body.force}")

    sync_payload = await gating_service.sync_init_state()

    # 也通过 SSE 推送给前端（确保所有连接都收到最新状态）
    await gating_service.push_sync_state(sync_payload)

    return create_success_response(
        data=sync_payload.model_dump(mode="json"),
        trace_id=trace_id,
    )


@router.get("/pending_count", response_model=ResponseModel)
async def get_pending_count(
    trace_id: str = Depends(get_trace_id),
    gating_service: GatingService = Depends(get_gating_service),
) -> ResponseModel:
    """获取当前 PENDING 状态的审批请求数量。

    做什么：用于前端调试面板显示当前积压的审批请求数量。
    为什么这样做：调试时可快速评估当前系统的审批负载。
    输出：ResponseModel - 包含 count 字段。
    """
    count = await gating_service.get_pending_count()

    return create_success_response(
        data={"count": count},
        trace_id=trace_id,
    )
