"""
MCP 工具：创建或写入文件。

做什么：将内容写入目标文件。支持 overwrite（覆盖）和 append（追加）两种模式。
        如果目标文件不存在且父目录存在，则自动创建文件。
风险等级：L2（高危，有明确副作用，需要前端 Gating 确认后方可执行）。
"""

from __future__ import annotations

import os
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import (
    DEFAULT_FILE_WRITE_MAX_SIZE,
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
            "description": "要写入的文件的绝对路径。",
            "minLength": 1,
            "maxLength": 1024,
        },
        "content": {
            "type": "string",
            "description": "要写入的文件内容。",
            "maxLength": DEFAULT_FILE_WRITE_MAX_SIZE,
        },
        "mode": {
            "type": "string",
            "enum": ["overwrite", "append"],
            "description": "写入模式：'overwrite' 覆盖写入，'append' 追加写入。默认 'overwrite'。",
            "default": "overwrite",
        },
    },
    "required": ["path", "content"],
}


async def handle_create_or_write_file(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    创建或写入文件（Risk Level L2）。

    参数:
        parameters: 包含 path, content（必填）和 mode（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(
        f"写入文件请求 trace_id={trace_id} parameters_keys={list(parameters.keys())}"
    )

    path: str = parameters.get("path", "")
    content: str = parameters.get("content", "")
    mode: str = parameters.get("mode", "overwrite")

    # 验证目标路径安全性
    try:
        abs_path = validate_path_safety(path, allow_nonexistent=True)
    except ValueError as exc:
        logger.warning(f"写入文件失败 trace_id={trace_id} path={path} 原因: {exc!s}")
        return f"【操作拒绝】路径验证失败: {exc!s}"

    # 检查父目录是否存在
    parent_dir = os.path.dirname(abs_path)
    if not os.path.isdir(parent_dir):
        logger.warning(
            f"写入文件失败 trace_id={trace_id} path={abs_path} 原因: 父目录不存在: {parent_dir}"
        )
        return f"【操作错误】目标路径的父目录不存在: {parent_dir}"

    # 检查内容大小
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > DEFAULT_FILE_WRITE_MAX_SIZE:
        logger.warning(
            f"写入文件失败 trace_id={trace_id} path={abs_path} "
            f"原因: 内容大小 {len(content_bytes)} 超过限制 {DEFAULT_FILE_WRITE_MAX_SIZE}"
        )
        return (
            f"【操作拒绝】写入内容过大。"
            f"内容大小: {format_file_size(len(content_bytes))}，"
            f"上限: {format_file_size(DEFAULT_FILE_WRITE_MAX_SIZE)}。"
        )

    # 检查文件是否已存在
    file_exists = os.path.isfile(abs_path)
    if file_exists and mode == "overwrite":
        logger.info(f"写入文件将覆盖已有文件 trace_id={trace_id} path={abs_path}")

    # 执行写入
    try:
        write_mode = "a" if mode == "append" else "w"
        with open(abs_path, mode=write_mode, encoding="utf-8") as f:
            f.write(content)
    except PermissionError as exc:
        logger.warning(f"写入文件失败 trace_id={trace_id} path={abs_path} 原因: 权限不足 {exc!s}")
        return f"【权限错误】没有权限写入目标文件: {exc!s}"
    except OSError as exc:
        logger.warning(f"写入文件失败 trace_id={trace_id} path={abs_path} 原因: 系统错误 {exc!s}")
        return f"【系统错误】写入文件时发生错误: {exc!s}"

    # 获取最终文件大小
    try:
        final_size = os.path.getsize(abs_path)
    except OSError:
        final_size = len(content_bytes)

    mode_desc = "覆盖写入" if mode == "overwrite" else "追加写入"
    exists_desc = "（新建文件）" if not file_exists else "（已存在文件）"

    logger.info(
        f"写入文件成功 trace_id={trace_id} path={abs_path} mode={mode} size={final_size}"
    )
    return (
        f"✅ 文件{ mode_desc }成功 {exists_desc}\n"
        f"   路径: {abs_path}\n"
        f"   写入大小: {format_file_size(final_size)}\n"
        f"   写入模式: {mode}"
    )
