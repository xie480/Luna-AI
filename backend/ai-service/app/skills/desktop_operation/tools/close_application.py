"""
MCP 工具：关闭应用程序。

做什么：通过进程名或 PID 关闭指定软件，优先尝试优雅退出（发送关闭信号），
         超时后可强制终止，并返回操作结果。
风险等级：L2（中危，终止进程可能导致未保存数据丢失，需要用户确认）。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.skills.desktop_operation.base import (
    DEFAULT_CLOSE_TIMEOUT,
    build_error_result,
    build_success_result,
    find_process_by_name,
    find_process_by_pid,
    terminate_process_force,
    terminate_process_graceful,
)

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pid": {
            "type": "integer",
            "description": "目标进程 ID。与 process_name 二选一，优先使用 PID 精确匹配。",
        },
        "process_name": {
            "type": "string",
            "description": "目标进程名称（如 'notepad.exe'、'chrome'）。与 pid 二选一。",
            "minLength": 1,
            "maxLength": 256,
        },
        "force": {
            "type": "boolean",
            "description": "是否跳过优雅退出直接强制终止。默认 false（先尝试优雅退出，超时后强制）。",
            "default": False,
        },
        "timeout": {
            "type": "number",
            "description": "优雅退出等待超时秒数，默认 5.0。仅在 force=false 时有效。",
            "default": 5.0,
            "minimum": 0.5,
            "maximum": 60.0,
        },
    },
    "required": [],
}


async def handle_close_application(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    关闭指定应用程序。

    参数:
        parameters: 包含 pid（可选）、process_name（可选）、
                    force（可选）、timeout（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(f"关闭应用请求 trace_id={trace_id} parameters={parameters}")

    pid: int | None = parameters.get("pid")
    process_name: str = parameters.get("process_name", "").strip()
    force: bool = parameters.get("force", False)
    timeout: float = parameters.get("timeout", DEFAULT_CLOSE_TIMEOUT)

    # 参数校验：必须提供 pid 或 process_name 之一
    if pid is None and not process_name:
        return build_error_result(
            "参数错误",
            "必须提供 pid 或 process_name 参数之一",
        )

    # 确定目标进程
    target_pid: int | None = None
    target_name: str = ""

    if pid is not None:
        # 通过 PID 查找
        proc_info = find_process_by_pid(pid)
        if not proc_info:
            logger.warning(f"关闭应用失败 trace_id={trace_id} 原因: 进程不存在 PID={pid}")
            return build_error_result("进程不存在", f"未找到 PID 为 {pid} 的进程")
        target_pid = pid
        target_name = proc_info.get("name", "未知")
    else:
        # 通过进程名查找
        matched = find_process_by_name(process_name)
        if not matched:
            logger.warning(f"关闭应用失败 trace_id={trace_id} 原因: 进程未找到 name={process_name}")
            return build_error_result(
                "进程未找到",
                f"未找到名称为 '{process_name}' 的进程",
                suggestion="请确认进程正在运行，或使用 tasklist（Windows）/ ps（Linux/macOS）查看进程名",
            )

        if len(matched) > 1:
            # 多个匹配，列出供用户选择
            proc_list = "\n".join(
                f"  PID={p['pid']} 名称={p['name']} 状态={p['status']}"
                for p in matched[:10]  # 最多展示 10 条
            )
            logger.warning(
                f"关闭应用失败 trace_id={trace_id} 原因: 匹配到多个进程 name={process_name} count={len(matched)}"
            )
            return build_error_result(
                "进程不唯一",
                f"找到 {len(matched)} 个匹配 '{process_name}' 的进程，请使用 PID 精确指定：\n{proc_list}",
            )

        target_pid = matched[0]["pid"]
        target_name = matched[0]["name"]

    # 执行关闭
    if force:
        # 直接强制终止
        success, msg = terminate_process_force(target_pid)
        method = "强制终止"
    else:
        # 先尝试优雅退出
        success, msg = terminate_process_graceful(target_pid, timeout)
        method = "优雅退出"

        if not success and "未响应" in msg:
            # 优雅退出超时，自动降级为强制终止
            logger.info(
                f"关闭应用降级 trace_id={trace_id} PID={target_pid} 优雅退出超时，尝试强制终止"
            )
            success, msg = terminate_process_force(target_pid)
            method = "强制终止（优雅退出超时后降级）"

    if not success:
        logger.warning(f"关闭应用失败 trace_id={trace_id} PID={target_pid} 原因: {msg}")
        return build_error_result("关闭失败", msg)

    result_extra: dict[str, Any] = {
        "进程PID": target_pid,
        "进程名": target_name,
        "关闭方式": method,
    }
    if not force and timeout != DEFAULT_CLOSE_TIMEOUT:
        result_extra["超时设置"] = f"{timeout}s"

    logger.info(f"关闭应用成功 trace_id={trace_id} PID={target_pid} 方式={method}")
    return build_success_result(f"应用程序已关闭 (PID={target_pid})", result_extra)
