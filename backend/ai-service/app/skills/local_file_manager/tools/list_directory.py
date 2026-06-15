"""
MCP 工具：列出指定目录下的文件和文件夹。

做什么：安全遍历指定目录，返回目录下所有文件和子文件夹的列表。
        每个条目包含名称、类型（文件/目录）和大小（仅文件）。
风险等级：L0（低危，无副作用，不需要前端 Gating 确认）。
"""

from __future__ import annotations

import os
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import (
    format_file_size,
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
            "description": "要列出内容的绝对目录路径。",
            "minLength": 1,
            "maxLength": 1024,
        },
    },
    "required": ["path"],
}


async def handle_list_directory(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    列出指定目录下的所有文件和文件夹。

    参数:
        parameters: 包含 path（必填）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 格式化后的目录内容列表文本。
    """
    logger.info(
        f"列出目录请求 trace_id={trace_id} parameters={parameters}"
    )

    path: str = parameters.get("path", "")

    # 验证路径安全性
    try:
        abs_path = validate_path_safety(path, allow_nonexistent=False)
    except ValueError as exc:
        logger.warning(f"列出目录失败 trace_id={trace_id} path={path} 原因: {exc!s}")
        return f"【操作拒绝】{exc!s}"

    # 确认是目录
    if not os.path.isdir(abs_path):
        logger.warning(f"列出目录失败 trace_id={trace_id} path={abs_path} 原因: 指定路径不是目录")
        return f"【操作错误】路径不是目录: {abs_path}"

    # 读取目录内容
    try:
        entries = os.listdir(abs_path)
    except PermissionError as exc:
        logger.warning(f"列出目录失败 trace_id={trace_id} path={abs_path} 原因: 权限不足 {exc!s}")
        return f"【权限错误】没有权限访问目标目录: {abs_path}"
    except OSError as exc:
        logger.warning(f"列出目录失败 trace_id={trace_id} path={abs_path} 原因: 系统错误 {exc!s}")
        return f"【系统错误】访问目录时发生错误: {exc!s}"

    # 排序：目录在前，文件在后
    dirs: list[str] = []
    files: list[dict[str, Any]] = []
    for entry in entries:
        full_path = os.path.join(abs_path, entry)
        try:
            if os.path.isdir(full_path):
                dirs.append(entry)
            elif os.path.isfile(full_path):
                files.append({"name": entry, "size": os.path.getsize(full_path)})
        except (OSError, PermissionError):
            continue

    dirs.sort(key=str.lower)
    files.sort(key=lambda x: x["name"].lower())

    # 格式化输出
    output_parts: list[str] = []
    output_parts.append(f"📁 目录: {abs_path}")
    output_parts.append(f"共 {len(dirs)} 个目录，{len(files)} 个文件")
    output_parts.append("")

    if dirs:
        output_parts.append("【目录】")
        for d in dirs:
            output_parts.append(f"  📂 {d}/")
        output_parts.append("")

    if files:
        output_parts.append("【文件】")
        for f in files:
            output_parts.append(f"  📄 {f['name']}  ({format_file_size(f['size'])})")
        output_parts.append("")

    if not dirs and not files:
        output_parts.append("（目录为空）")

    output_text: str = "\n".join(output_parts)

    logger.info(
        f"列出目录成功 trace_id={trace_id} path={abs_path} dirs={len(dirs)} files={len(files)}"
    )
    return output_text
