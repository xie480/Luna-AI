"""
MCP 工具：打开应用程序。

做什么：通过应用名称或可执行文件路径启动指定软件，支持传入启动参数。
         返回进程信息；对应用未找到、启动失败等情况进行错误处理。
风险等级：L1（低危，启动进程有副作用，但通常不涉及数据修改）。
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

from app.logger import logger
from app.skills.desktop_operation.base import (
    build_error_result,
    build_success_result,
)

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "app_name": {
            "type": "string",
            "description": "应用程序名称（如 'notepad'、'chrome'）或可执行文件的绝对路径。"
                           "传入名称时系统会尝试在 PATH 中查找；传入路径时直接使用。",
            "minLength": 1,
            "maxLength": 1024,
        },
        "arguments": {
            "type": "array",
            "items": {"type": "string", "maxLength": 1024},
            "description": "可选。启动参数列表，如 ['--new-window', 'https://example.com']。",
            "maxItems": 50,
        },
        "working_directory": {
            "type": "string",
            "description": "可选。进程的工作目录。",
            "maxLength": 1024,
        },
        "wait_for_start": {
            "type": "boolean",
            "description": "是否等待进程启动完成后再返回。默认 false（异步启动）。",
            "default": False,
        },
    },
    "required": ["app_name"],
}


async def handle_open_application(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    启动指定应用程序。

    参数:
        parameters: 包含 app_name（必填）、arguments（可选）、
                    working_directory（可选）、wait_for_start（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本，成功时包含 PID 和进程信息。
    """
    logger.info(f"打开应用请求 trace_id={trace_id} parameters={parameters}")

    app_name: str = parameters.get("app_name", "").strip()
    arguments: list[str] = parameters.get("arguments", [])
    working_directory: str = parameters.get("working_directory", "").strip()
    wait_for_start: bool = parameters.get("wait_for_start", False)

    if not app_name:
        return build_error_result("参数错误", "应用程序名称不能为空")

    # 解析应用路径
    resolved_path = _resolve_app_path(app_name)
    if not resolved_path:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 应用未找到 app_name={app_name}")
        return build_error_result(
            "应用未找到",
            f"未找到应用程序: {app_name}",
            suggestion="请确认应用已安装且在 PATH 中，或提供可执行文件的绝对路径",
        )

    # 构建启动命令
    cmd = [resolved_path] + arguments

    # 校验工作目录
    cwd = None
    if working_directory:
        if os.path.isdir(working_directory):
            cwd = working_directory
        else:
            logger.warning(
                f"打开应用警告 trace_id={trace_id} 工作目录不存在，使用默认目录: {working_directory}"
            )

    # 启动进程
    # 注意：Windows 下不使用 DETACHED_PROCESS / CREATE_NEW_CONSOLE 组合，
    # 该组合在部分 Windows 版本上会导致 WinError 87（参数错误）。
    # 使用默认标志即可满足 GUI 应用独立运行的需求。
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    except FileNotFoundError:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 可执行文件不存在 {resolved_path}")
        return build_error_result("应用未找到", f"可执行文件不存在: {resolved_path}")
    except PermissionError as exc:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 权限不足 {exc!s}")
        return build_error_result("权限错误", f"没有权限启动应用: {exc!s}")
    except OSError as exc:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 系统错误 {exc!s}")
        return build_error_result("系统错误", f"启动应用时发生系统错误: {exc!s}")
    except Exception as exc:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 未知异常 {exc!s}")
        return build_error_result("系统错误", f"启动应用时发生异常: {exc!s}")

    # 等待进程启动（可选）
    pid = process.pid
    proc_name = os.path.basename(resolved_path)

    if wait_for_start:
        import time
        # 短暂等待确认进程没有立即崩溃
        time.sleep(0.5)
        return_code = process.poll()
        if return_code is not None:
            logger.warning(
                f"打开应用失败 trace_id={trace_id} 原因: 进程启动后立即退出 "
                f"PID={pid} return_code={return_code}"
            )
            return build_error_result(
                "启动失败",
                f"应用程序启动后立即退出 (PID={pid}, 退出码={return_code})",
                suggestion="请检查启动参数是否正确，或尝试手动运行确认应用可正常启动",
            )

    result_extra: dict[str, Any] = {
        "进程PID": pid,
        "进程名": proc_name,
        "启动路径": resolved_path,
        "启动参数": " ".join(arguments) if arguments else "（无）",
    }
    if cwd:
        result_extra["工作目录"] = cwd

    logger.info(f"打开应用成功 trace_id={trace_id} PID={pid} 应用={proc_name}")
    return build_success_result(f"应用程序已启动 (PID={pid})", result_extra)


def _resolve_app_path(app_name: str) -> str | None:
    """
    解析应用程序的可执行文件路径。

    参数:
        app_name: 应用程序名称或路径。
    返回:
        str | None: 解析后的绝对路径，未找到返回 None。
    """
    # 如果传入的是绝对路径且文件存在，直接使用
    if os.path.isabs(app_name) and os.path.isfile(app_name):
        return os.path.abspath(app_name)

    # 如果传入的是相对路径且文件存在，转为绝对路径
    if os.path.isfile(app_name):
        return os.path.abspath(app_name)

    # 尝试在 PATH 中查找
    path_env = os.environ.get("PATH", "")
    system = platform.system()

    for path_dir in path_env.split(os.pathsep):
        if not path_dir:
            continue

        # 尝试常见可执行文件扩展名
        extensions = [""]
        if system == "Windows":
            extensions = ["", ".exe", ".bat", ".cmd", ".com", ".msi"]

        for ext in extensions:
            candidate = os.path.join(path_dir, app_name + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return os.path.abspath(candidate)

    # Windows 特有：尝试在常见安装目录查找
    if system == "Windows":
        common_dirs = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for base_dir in common_dirs:
            if not base_dir or not os.path.isdir(base_dir):
                continue
            try:
                for entry in os.listdir(base_dir):
                    entry_path = os.path.join(base_dir, entry)
                    if os.path.isdir(entry_path):
                        # 检查目录下是否有匹配的可执行文件
                        for ext in (".exe", ".bat", ".cmd"):
                            candidate = os.path.join(entry_path, app_name + ext)
                            if os.path.isfile(candidate):
                                return os.path.abspath(candidate)
            except (OSError, PermissionError):
                continue

    return None
