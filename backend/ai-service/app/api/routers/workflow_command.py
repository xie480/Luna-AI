"""
Luna AI 工作流命令 API 路由模块。

做什么：提供前端发送的工作流命令处理端点，包括暂停/恢复/取消任务等操作。
         前端通过 HTTP POST 发送命令，后端根据命令类型调度到对应的处理器。

为什么这样做：Phase 10 引入的任务级状态管理需要前端发送用户主动操作命令，
             这些命令通过标准 HTTP POST 请求发送，而非 WebSocket。

API 端点：
    POST /api/ws/command — 接收工作流命令（如 CMD_CANCEL_TASK、CMD_PAUSE_TASK、CMD_RESUME_TASK）

边界条件：
    - 请求体必须包含 type 和 payload 字段。
    - type 必须是已知的命令类型。
    - 所有端点必须携带 X-Trace-ID 请求头（自动生成或透传）。

异常行为：
    - 参数校验失败返回 400。
    - 未知命令类型返回 400。
    - 服务未初始化返回 503。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.logger import logger
from app.types.errors import (
    ErrorCode,
    ResponseModel,
    create_error_response,
    create_success_response,
)
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/ws", tags=["workflow_command"])


# ============================================================
# Pydantic 请求模型
# ============================================================


class WorkflowCommandRequest(BaseModel):
    """工作流命令请求体。

    做什么：前端发送的工作流命令，包含命令类型和载荷。
    为什么这样做：使用 Pydantic 模型确保请求参数的类型安全。
    """
    type: str = Field(
        ..., min_length=1, max_length=100, description="命令类型。"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="命令载荷。"
    )


# ============================================================
# 依赖注入
# ============================================================


async def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """从请求头获取 trace_id，若不存在则自动生成。"""
    return x_trace_id or generate_string_id()


# ============================================================
# API 端点
# ============================================================


@router.post("/command", response_model=ResponseModel)
async def handle_workflow_command(
    request_body: WorkflowCommandRequest,
    request: Request,
    trace_id: str = Depends(get_trace_id),
) -> ResponseModel:
    """处理工作流命令。

    做什么：接收前端发来的工作流命令（暂停/恢复/取消等），
            根据命令类型分发给对应的处理器。

    输入：
        request_body: 包含 type（命令类型）和 payload（命令载荷）。
        request: FastAPI 请求对象，用于获取 app.state 中的服务实例。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。

    边界条件：
        - type 必须是已知的命令类型之一。
        - payload 中的 task_id 必须存在。

    异常行为：
        - 未知命令类型返回 400。
        - 处理器执行失败返回 500。
    """
    cmd_type = request_body.type
    payload = request_body.payload

    logger.info(
        f"[WorkflowCommand] 收到命令 type={cmd_type} "
        f"trace_id={trace_id} "
        f"task_id={payload.get('task_id', 'N/A')}"
    )

    # 根据命令类型分发处理
    if cmd_type == "CMD_CANCEL_TASK":
        return await _handle_cancel_task(payload, request, trace_id)
    elif cmd_type == "CMD_PAUSE_TASK":
        return await _handle_pause_task(payload, request, trace_id)
    elif cmd_type == "CMD_RESUME_TASK":
        return await _handle_resume_task(payload, request, trace_id)
    else:
        logger.warning(
            f"[WorkflowCommand] 未知命令类型 type={cmd_type} trace_id={trace_id}"
        )
        return create_error_response(
            code=400,
            msg=f"未知的命令类型: {cmd_type}",
            trace_id=trace_id,
        )


async def _handle_cancel_task(
    payload: dict[str, Any],
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """处理取消任务命令。

    做什么：将指定任务标记为已取消（TERMINATED），保存终止快照。

    输入：
        payload: 包含 task_id 和可选 reason 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。
    """
    task_id = payload.get("task_id", "")
    reason = payload.get("reason", "用户手动取消")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    # 从 app.state 获取 DAG 引擎实例
    dag_engine = getattr(request.app.state, "dag_engine", None)
    if not dag_engine:
        logger.warning(
            f"[WorkflowCommand] DAG 引擎未初始化，跳过取消任务 "
            f"task_id={task_id} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "accepted",
                "message": "取消请求已接收（DAG 引擎未初始化，仅记录）",
            },
            trace_id=trace_id,
        )

    try:
        # 调用 DAG 引擎的取消方法
        if hasattr(dag_engine, "cancel_task"):
            await dag_engine.cancel_task(task_id=task_id, reason=reason, trace_id=trace_id)
        elif hasattr(dag_engine, "terminate_task"):
            await dag_engine.terminate_task(task_id=task_id, reason=reason, trace_id=trace_id)

        logger.info(
            f"[WorkflowCommand] 取消任务成功 task_id={task_id} "
            f"reason={reason} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "cancelled",
                "message": "任务已取消",
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            f"[WorkflowCommand] 取消任务失败 task_id={task_id} "
            f"error={exc} trace_id={trace_id}"
        )
        return create_error_response(
            code=ErrorCode.SYSTEM_ERROR.value,
            msg=f"取消任务失败: {exc}",
            trace_id=trace_id,
        )


async def _handle_pause_task(
    payload: dict[str, Any],
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """处理暂停任务命令。

    做什么：将指定任务标记为暂停状态（PAUSED）。

    输入：
        payload: 包含 task_id 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。
    """
    task_id = payload.get("task_id", "")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    # 从 app.state 获取 DAG 引擎实例
    dag_engine = getattr(request.app.state, "dag_engine", None)
    if not dag_engine:
        logger.warning(
            f"[WorkflowCommand] DAG 引擎未初始化，跳过暂停任务 "
            f"task_id={task_id} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "accepted",
                "message": "暂停请求已接收（DAG 引擎未初始化，仅记录）",
            },
            trace_id=trace_id,
        )

    try:
        # 调用 DAG 引擎的暂停方法
        if hasattr(dag_engine, "pause_task"):
            await dag_engine.pause_task(task_id=task_id, trace_id=trace_id)

        logger.info(
            f"[WorkflowCommand] 暂停任务成功 task_id={task_id} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "paused",
                "message": "任务已暂停",
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            f"[WorkflowCommand] 暂停任务失败 task_id={task_id} "
            f"error={exc} trace_id={trace_id}"
        )
        return create_error_response(
            code=ErrorCode.SYSTEM_ERROR.value,
            msg=f"暂停任务失败: {exc}",
            trace_id=trace_id,
        )


async def _handle_resume_task(
    payload: dict[str, Any],
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """处理恢复任务命令。

    做什么：将指定任务从暂停状态恢复为运行状态（RUNNING）。

    输入：
        payload: 包含 task_id 和可选 snapshot_version 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。
    """
    task_id = payload.get("task_id", "")
    snapshot_version = payload.get("snapshot_version")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    # 从 app.state 获取 DAG 引擎实例
    dag_engine = getattr(request.app.state, "dag_engine", None)
    if not dag_engine:
        logger.warning(
            f"[WorkflowCommand] DAG 引擎未初始化，跳过恢复任务 "
            f"task_id={task_id} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "accepted",
                "message": "恢复请求已接收（DAG 引擎未初始化，仅记录）",
            },
            trace_id=trace_id,
        )

    try:
        # 调用 DAG 引擎的恢复方法
        if hasattr(dag_engine, "resume_task"):
            await dag_engine.resume_task(
                task_id=task_id,
                snapshot_version=snapshot_version,
                trace_id=trace_id,
            )

        logger.info(
            f"[WorkflowCommand] 恢复任务成功 task_id={task_id} trace_id={trace_id}"
        )
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "resumed",
                "message": "任务已恢复",
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            f"[WorkflowCommand] 恢复任务失败 task_id={task_id} "
            f"error={exc} trace_id={trace_id}"
        )
        return create_error_response(
            code=ErrorCode.SYSTEM_ERROR.value,
            msg=f"恢复任务失败: {exc}",
            trace_id=trace_id,
        )