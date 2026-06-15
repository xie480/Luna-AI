"""
MCP 工具：移动或重命名文件/目录。

做什么：将源文件或目录移动到目标路径。如果源和目标在同一父目录下，则为重命名操作。
        若目标已存在且 overwrite=True 则覆盖，否则拒绝。
风险等级：L2（高危，有明确副作用，需要前端 Gating 确认后方可执行）。
"""

from __future__ import annotations

import os
import shutil
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import validate_path_safety

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_path": {
            "type": "string",
            "description": "源文件或目录的绝对路径。",
            "minLength": 1,
            "maxLength": 1024,
        },
        "destination_path": {
            "type": "string",
            "description": "目标文件或目录的绝对路径。",
            "minLength": 1,
            "maxLength": 1024,
        },
        "overwrite": {
            "type": "boolean",
            "description": "如果目标已存在，是否覆盖。默认 false。",
            "default": False,
        },
    },
    "required": ["source_path", "destination_path"],
}


async def handle_move_or_rename_file(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    移动或重命名文件/目录（Risk Level L2）。

    参数:
        parameters: 包含 source_path, destination_path（必填）和 overwrite（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(
        f"移动/重命名文件请求 trace_id={trace_id} parameters={parameters}"
    )

    source_path: str = parameters.get("source_path", "")
    destination_path: str = parameters.get("destination_path", "")
    overwrite: bool = parameters.get("overwrite", False)

    # 验证源路径安全性（必须存在）
    try:
        abs_source = validate_path_safety(source_path, allow_nonexistent=False)
    except ValueError as exc:
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} source={source_path} 原因: {exc!s}"
        )
        return f"【操作拒绝】源路径验证失败: {exc!s}"

    # 验证目标路径安全性（允许不存在，但父目录必须在保护区外）
    try:
        abs_dest = validate_path_safety(destination_path, allow_nonexistent=True)
    except ValueError as exc:
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} destination={destination_path} 原因: {exc!s}"
        )
        return f"【操作拒绝】目标路径验证失败: {exc!s}"

    # 检查目标父目录是否存在
    dest_parent = os.path.dirname(abs_dest)
    if not os.path.isdir(dest_parent):
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} "
            f"source={abs_source} dest={abs_dest} 原因: 目标父目录不存在: {dest_parent}"
        )
        return f"【操作错误】目标路径的父目录不存在: {dest_parent}"

    # 检查目标是否已存在
    if os.path.exists(abs_dest) and not overwrite:
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} "
            f"source={abs_source} dest={abs_dest} 原因: 目标已存在且 overwrite=False"
        )
        return (
            f"【操作拒绝】目标路径已存在: {abs_dest}。"
            f"如需覆盖请设置 overwrite=True。"
        )

    # 执行移动/重命名
    try:
        shutil.move(src=abs_source, dst=abs_dest)
    except PermissionError as exc:
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} "
            f"source={abs_source} dest={abs_dest} 原因: 权限不足 {exc!s}"
        )
        return f"【权限错误】没有权限执行移动/重命名操作: {exc!s}"
    except (shutil.Error, OSError) as exc:
        logger.warning(
            f"移动/重命名失败 trace_id={trace_id} "
            f"source={abs_source} dest={abs_dest} 原因: {exc!s}"
        )
        return f"【系统错误】移动/重命名操作失败: {exc!s}"

    logger.info(
        f"移动/重命名成功 trace_id={trace_id} source={abs_source} dest={abs_dest}"
    )
    return (
        f"✅ 移动/重命名成功\n"
        f"   源路径: {abs_source}\n"
        f"   目标路径: {abs_dest}\n"
        f"   覆盖模式: {'是' if overwrite else '否'}"
    )
