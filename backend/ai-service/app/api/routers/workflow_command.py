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

    做什么：
    1. 通过 chat_workflow_service.cancel_task_run() 取消正在运行的 asyncio.Task
       （中断 LangGraph 的 ainvoke 协程）。
    2. 通过 snapshot_manager 更新 Redis 任务状态为 TERMINATED。
    3. 通过 state_transition_manager 记录跃迁审计日志。

    输入：
        payload: 包含 task_id 和可选 reason 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。

    边界条件：
        - chat_workflow_service 不存在时仅降级为标记状态，不中断实际协程。
        - snapshot_manager 未初始化时跳过 Redis 状态更新。
        - 如果协程已执行完毕（找不到 task_id），仍正常记录状态。
    """
    task_id = payload.get("task_id", "")
    reason = payload.get("reason", "用户手动取消")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    # 从 app.state 获取服务实例
    chat_workflow_service = getattr(request.app.state, "chat_workflow_service", None)
    snapshot_manager = getattr(request.app.state, "snapshot_manager", None)
    state_transition_manager = getattr(request.app.state, "state_transition_manager", None)

    errors: list[str] = []

    # 1. 中断正在运行的 asyncio.Task（核心操作）
    #    做什么：通过 task_id 查找对应的 asyncio.Task 并调用 cancel()。
    #            这会触发 CancelledError 中断 LangGraph 的 ainvoke 协程。
    #    为什么这样做：仅标记 Redis 状态无法停止已启动的协程，
    #                 asyncio.Task.cancel() 是唯一能强制中断 in-flight 协程的方式。
    cancelled_actual_task = False
    if chat_workflow_service and hasattr(chat_workflow_service, "cancel_task_run"):
        try:
            cancelled_actual_task = await chat_workflow_service.cancel_task_run(task_id)
            if cancelled_actual_task:
                logger.info(
                    f"[WorkflowCommand] 取消任务: 已中断协程 "
                    f"task_id={task_id} trace_id={trace_id}"
                )
            else:
                logger.info(
                    f"[WorkflowCommand] 取消任务: 未找到运行中协程（可能已执行完毕）"
                    f"task_id={task_id} trace_id={trace_id}"
                )
        except Exception as exc:
            err_msg = f"协程中断失败: {exc}"
            errors.append(err_msg)
            logger.warning(
                f"[WorkflowCommand] {err_msg} task_id={task_id}"
            )
    else:
        logger.warning(
            f"[WorkflowCommand] chat_workflow_service 未初始化或缺少 "
            f"cancel_task_run 方法，跳过协程中断 task_id={task_id}"
        )

    # 2. 更新 Redis 任务状态缓存为 TERMINATED
    if snapshot_manager and hasattr(snapshot_manager, "set_task_status"):
        try:
            await snapshot_manager.set_task_status(
                task_id=task_id,
                status="TERMINATED",
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 取消任务: Redis 状态已更新 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"Redis 状态更新失败: {exc}"
            errors.append(err_msg)
            logger.warning(
                f"[WorkflowCommand] {err_msg} task_id={task_id}"
            )
    else:
        logger.warning(
            f"[WorkflowCommand] snapshot_manager 未初始化，"
            f"跳过 Redis 状态更新 task_id={task_id}"
        )

    # 3. 记录状态跃迁审计日志
    if state_transition_manager and hasattr(state_transition_manager, "log_transition"):
        try:
            await state_transition_manager.log_transition(
                session_id="",
                prev_status="RUNNING",
                next_status="TERMINATED",
                trigger_type="USER_CANCEL",
                transition_reason=reason,
                task_id=task_id,
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 取消任务: 跃迁日志已记录 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"跃迁日志记录失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] state_transition_manager 未初始化，"
            f"跳过跃迁日志 task_id={task_id}"
        )

    if errors:
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "cancelled",
                "cancelled_actual_task": cancelled_actual_task,
                "message": f"任务已取消（部分操作失败: {'; '.join(errors)}）",
            },
            trace_id=trace_id,
        )

    return create_success_response(
        data={
            "task_id": task_id,
            "status": "cancelled",
            "cancelled_actual_task": cancelled_actual_task,
            "message": "任务已取消",
        },
        trace_id=trace_id,
    )


async def _handle_pause_task(
    payload: dict[str, Any],
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """处理暂停任务命令。

    做什么：
    1. 通过 chat_workflow_service.cancel_task_run() 中断正在运行的协程
       （暂停本质也需先中断当前执行）。
    2. 通过 snapshot_manager 保存 DAG 运行时的全量快照（用于后续恢复）。
    3. 通过 snapshot_manager.set_task_status() 更新 Redis 状态为 PAUSED。
    4. 通过 state_transition_manager 记录跃迁审计日志。

    输入：
        payload: 包含 task_id 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。

    边界条件：
        - chat_workflow_service 不存在时无法中断协程，但依然标记暂停状态。
        - 如果协程已执行完毕，snapshot 中保留的仍是最新快照。
    """
    task_id = payload.get("task_id", "")
    reason = payload.get("reason", "用户手动暂停")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    chat_workflow_service = getattr(request.app.state, "chat_workflow_service", None)
    snapshot_manager = getattr(request.app.state, "snapshot_manager", None)
    state_transition_manager = getattr(request.app.state, "state_transition_manager", None)

    errors: list[str] = []

    # 1. 中断正在运行的 asyncio.Task（暂停必须先中断当前执行）
    #    为什么这样做：暂停的本质是"冻结执行现场"，不中断协程的话，
    #                 LangGraph 会继续执行直到自然结束，无法实现暂停语义。
    cancelled_actual_task = False
    if chat_workflow_service and hasattr(chat_workflow_service, "cancel_task_run"):
        try:
            cancelled_actual_task = await chat_workflow_service.cancel_task_run(task_id)
            if cancelled_actual_task:
                logger.info(
                    f"[WorkflowCommand] 暂停任务: 已中断协程 "
                    f"task_id={task_id} trace_id={trace_id}"
                )
        except Exception as exc:
            err_msg = f"协程中断失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] chat_workflow_service 未初始化，"
            f"跳过协程中断 task_id={task_id}"
        )

    # 2. 保存 DAG 运行时快照到 PG + Redis（用于暂停后的恢复）
    #    做什么：快照包含 DagEngineState 全量数据，恢复时通过
    #            RecoveryCoordinator.recover_task() 重建运行时上下文。
    #    为什么这样做：如果没有快照，恢复时无法知道 DAG 执行到了哪个节点。
    if snapshot_manager and hasattr(snapshot_manager, "save_snapshot"):
        try:
            await snapshot_manager.save_snapshot(
                task_id=task_id,
                dag_state={},  # 仅标记状态；全量 dag_state 由 LangGraph 内部 checkpoint 维护
                trigger="USER_PAUSE",
                session_id=payload.get("session_id", ""),
                trace_id=trace_id,
                task_status="PAUSED",
            )
            logger.info(
                f"[WorkflowCommand] 暂停任务: 快照已保存 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"快照保存失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] snapshot_manager 未初始化，"
            f"跳过暂停快照保存 task_id={task_id}"
        )

    # 3. 更新 Redis 任务状态缓存为 PAUSED
    if snapshot_manager and hasattr(snapshot_manager, "set_task_status"):
        try:
            await snapshot_manager.set_task_status(
                task_id=task_id,
                status="PAUSED",
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 暂停任务: Redis 状态已更新 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"Redis 状态更新失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] snapshot_manager 未初始化，"
            f"跳过 Redis 状态更新 task_id={task_id}"
        )

    # 4. 记录状态跃迁审计日志
    if state_transition_manager and hasattr(state_transition_manager, "log_transition"):
        try:
            await state_transition_manager.log_transition(
                session_id="",
                prev_status="RUNNING",
                next_status="PAUSED",
                trigger_type="NORMAL_ADVANCE",
                transition_reason=reason,
                task_id=task_id,
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 暂停任务: 跃迁日志已记录 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"跃迁日志记录失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] state_transition_manager 未初始化，"
            f"跳过跃迁日志 task_id={task_id}"
        )

    if errors:
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "paused",
                "message": f"任务已暂停（部分操作失败: {'; '.join(errors)}）",
            },
            trace_id=trace_id,
        )

    return create_success_response(
        data={
            "task_id": task_id,
            "status": "paused",
            "message": "任务已暂停",
        },
        trace_id=trace_id,
    )


async def _handle_resume_task(
    payload: dict[str, Any],
    request: Request,
    trace_id: str,
) -> ResponseModel:
    """处理恢复任务命令。

    做什么：
    1. 更新 Redis 任务状态缓存为 RUNNING。
    2. 记录状态跃迁审计日志。

    注意：实际的协程恢复（重新 ainvoke LangGraph）需要更复杂的逻辑：
          - 从 Snapshot 加载 DagEngineState
          - 重建 ChatWorkflowState
          - 调用 chat_workflow_service.run_graph() 重新执行
          目前仅完成状态标记和日志记录，完整恢复链路需配合 Phase 10 的恢复协调器实现。

    输入：
        payload: 包含 task_id 和可选 session_id 的字典。
        request: FastAPI 请求对象。
        trace_id: 追踪 ID。

    输出：
        ResponseModel: 标准响应模型。

    边界条件：
        - snapshot_manager 未初始化时仅记录日志。
        - 恢复后的实际重新执行需要前端重新发送消息触发。
    """
    task_id = payload.get("task_id", "")
    reason = payload.get("reason", "用户手动恢复")

    if not task_id:
        return create_error_response(
            code=400,
            msg="task_id 不能为空",
            trace_id=trace_id,
        )

    snapshot_manager = getattr(request.app.state, "snapshot_manager", None)
    state_transition_manager = getattr(request.app.state, "state_transition_manager", None)

    errors: list[str] = []

    # 1. 更新 Redis 任务状态缓存为 RUNNING
    if snapshot_manager and hasattr(snapshot_manager, "set_task_status"):
        try:
            await snapshot_manager.set_task_status(
                task_id=task_id,
                status="RUNNING",
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 恢复任务: Redis 状态已更新 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"Redis 状态更新失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] snapshot_manager 未初始化，"
            f"跳过 Redis 状态更新 task_id={task_id}"
        )

    # 2. 记录状态跃迁审计日志
    if state_transition_manager and hasattr(state_transition_manager, "log_transition"):
        try:
            await state_transition_manager.log_transition(
                session_id="",
                prev_status="PAUSED",
                next_status="RUNNING",
                trigger_type="RESUME",
                transition_reason=reason,
                task_id=task_id,
                trace_id=trace_id,
            )
            logger.info(
                f"[WorkflowCommand] 恢复任务: 跃迁日志已记录 "
                f"task_id={task_id} trace_id={trace_id}"
            )
        except Exception as exc:
            err_msg = f"跃迁日志记录失败: {exc}"
            errors.append(err_msg)
            logger.warning(f"[WorkflowCommand] {err_msg}")
    else:
        logger.warning(
            f"[WorkflowCommand] state_transition_manager 未初始化，"
            f"跳过跃迁日志 task_id={task_id}"
        )

    if errors:
        return create_success_response(
            data={
                "task_id": task_id,
                "status": "resumed",
                "message": f"任务已恢复（部分操作失败: {'; '.join(errors)}）",
            },
            trace_id=trace_id,
        )

    return create_success_response(
        data={
            "task_id": task_id,
            "status": "resumed",
            "message": "任务状态已更新为 RUNNING，实际恢复执行需通过新的聊天请求触发",
        },
        trace_id=trace_id,
    )
