"""
MCP 工具：删除文件或目录。

做什么：删除指定文件或目录。如果是目录且 recursive=True，则递归删除所有子内容。
风险等级：L3（极高危，不可逆操作，必须由前端 Gating 强警告确认后方可执行）。
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import (
    make_writable,
    remove_readonly,
    validate_path_safety,
)

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "【极高危】要删除的文件或目录的绝对路径。必须确保路径完全正确且不是系统保护目录。",
            "minLength": 1,
            "maxLength": 1024,
        },
        "recursive": {
            "type": "boolean",
            "description": "如果是目录，是否递归删除其下所有内容。默认 false。",
            "default": False,
        },
    },
    "required": ["path"],
}


async def handle_delete_local_file(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    删除文件或目录（Risk Level L3 — 最高危险等级）。

    参数:
        parameters: 包含 path（必填）和 recursive（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(f"删除文件请求 trace_id={trace_id} parameters={parameters}")

    path: str = parameters.get("path", "")
    recursive: bool = parameters.get("recursive", False)

    # 验证路径安全性（必须存在）
    try:
        abs_path = validate_path_safety(path, allow_nonexistent=False)
    except ValueError as exc:
        logger.warning(f"删除文件失败 trace_id={trace_id} path={path} 原因: {exc!s}")
        return f"【操作拒绝】路径验证失败: {exc!s}"

    is_dir = os.path.isdir(abs_path)

    # 如果是目录且没有递归标志，但目录非空
    if is_dir and not recursive:
        try:
            dir_contents = os.listdir(abs_path)
        except PermissionError:
            dir_contents = ["（无法访问的条目）"]
        if dir_contents:
            logger.warning(
                f"删除目录失败 trace_id={trace_id} path={abs_path} "
                f"原因: 目录非空且 recursive=False，包含 {len(dir_contents)} 个子条目"
            )
            return (
                f"【操作拒绝】目录非空且未设置递归删除：{abs_path}\n"
                f"目录包含 {len(dir_contents)} 个子条目。如需删除请设置 recursive=True。"
            )

    # 执行删除
    try:
        if is_dir:
            if recursive:
                make_writable(abs_path)
            shutil.rmtree(abs_path, ignore_errors=False)
        else:
            remove_readonly(abs_path)
            os.remove(abs_path)
    except PermissionError as exc:
        logger.warning(f"删除失败 trace_id={trace_id} path={abs_path} 原因: 权限不足 {exc!s}")
        return f"【权限错误】没有权限删除目标: {exc!s}"
    except OSError as exc:
        logger.warning(f"删除失败 trace_id={trace_id} path={abs_path} 原因: 系统错误 {exc!s}")
        return f"【系统错误】删除操作失败: {exc!s}"

    target_type = "目录" if is_dir else "文件"
    logger.info(
        f"删除成功 trace_id={trace_id} path={abs_path} type={target_type} recursive={recursive}"
    )
    return (
        f"✅ 删除{target_type}成功\n"
        f"   路径: {abs_path}\n"
        f"   递归删除: {'是' if recursive and is_dir else '否'}"
    )
