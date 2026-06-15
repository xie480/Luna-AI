"""
MCP 工具：读取文件元数据。

做什么：获取文件的大小、创建时间、最后修改时间、最后访问时间等信息。
        不读取文件实际内容，仅限于元数据层面。
风险等级：L0（低危，无副作用，不需要前端 Gating 确认）。
"""

from __future__ import annotations

import os
import platform
import stat
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import (
    format_file_size,
    format_timestamp,
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
            "description": "目标文件的绝对路径。必须是已存在的文件而不是目录。",
            "minLength": 1,
            "maxLength": 1024,
        },
    },
    "required": ["path"],
}

# 常见文本文件扩展名列表
_TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".json",
    ".yaml", ".yml", ".xml", ".html", ".css", ".csv",
    ".ini", ".cfg", ".conf", ".log", ".env",
})


async def handle_read_file_metadata(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    读取指定文件的元数据信息。

    参数:
        parameters: 包含 path（必填）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 格式化后的文件元数据文本。
    """
    logger.info(
        f"读取文件元数据请求 trace_id={trace_id} parameters={parameters}"
    )

    path: str = parameters.get("path", "")

    # 验证路径安全性
    try:
        abs_path = validate_path_safety(path, allow_nonexistent=False)
    except ValueError as exc:
        logger.warning(f"读取文件元数据失败 trace_id={trace_id} path={path} 原因: {exc!s}")
        return f"【操作拒绝】{exc!s}"

    # 确认是文件
    if not os.path.isfile(abs_path):
        if os.path.isdir(abs_path):
            logger.warning(f"读取文件元数据失败 trace_id={trace_id} path={abs_path} 原因: 路径是目录")
            return f"【操作错误】路径是目录而非文件: {abs_path}"
        logger.warning(f"读取文件元数据失败 trace_id={trace_id} path={abs_path} 原因: 不是常规文件")
        return f"【操作错误】路径不是常规文件: {abs_path}"

    # 读取元数据
    try:
        file_stat = os.stat(abs_path)
    except PermissionError as exc:
        logger.warning(
            f"读取文件元数据失败 trace_id={trace_id} path={abs_path} 原因: 权限不足 {exc!s}"
        )
        return f"【权限错误】没有权限读取目标文件的元数据: {abs_path}"
    except OSError as exc:
        logger.warning(
            f"读取文件元数据失败 trace_id={trace_id} path={abs_path} 原因: 系统错误 {exc!s}"
        )
        return f"【系统错误】读取元数据时发生错误: {exc!s}"

    # 解析元数据
    file_size: int = file_stat.st_size
    if platform.system() == "Windows":
        created_time: float = file_stat.st_ctime
    else:
        created_time = getattr(file_stat, "st_birthtime", file_stat.st_ctime)
    modified_time: float = file_stat.st_mtime
    accessed_time: float = file_stat.st_atime

    file_mode: int = file_stat.st_mode
    is_readonly: bool = not bool(file_mode & stat.S_IWRITE)
    _, file_ext = os.path.splitext(abs_path)
    file_name = os.path.basename(abs_path)

    # 格式化输出
    output_parts: list[str] = []
    output_parts.append(f"📄 文件: {file_name}")
    output_parts.append(f"   完整路径: {abs_path}")
    output_parts.append(f"   大小: {format_file_size(file_size)} ({file_size} 字节)")
    output_parts.append(f"   类型: {file_ext if file_ext else '（无扩展名）'}")
    output_parts.append(f"   创建时间: {format_timestamp(created_time)}")
    output_parts.append(f"   修改时间: {format_timestamp(modified_time)}")
    output_parts.append(f"   访问时间: {format_timestamp(accessed_time)}")
    output_parts.append(f"   只读: {'是' if is_readonly else '否'}")

    is_text = file_ext.lower() in _TEXT_FILE_EXTENSIONS
    output_parts.append(f"   预估可读内容: {'是（文本文件）' if is_text else '否（二进制文件）'}")

    output_text: str = "\n".join(output_parts)

    logger.info(
        f"读取文件元数据成功 trace_id={trace_id} path={abs_path} size={file_size}"
    )
    return output_text
