"""
Local File Manager Skill 包初始化文件。

做什么：提供本地文件系统的安全读写与管理能力。
         包含目录遍历、文件搜索、元数据读取、移动/重命名、写入/创建、删除等工具。
         覆盖 L0 ~ L3 风险等级，用于验证 Phase 13 权限治理与前端 Gating 机制。
"""

from app.skills.local_file_manager.base import ALL_TOOL_NAMES
from app.skills.local_file_manager.tools import (
    TOOL_HANDLERS,
    TOOL_PARAMETER_SCHEMAS,
    handle_create_or_write_file,
    handle_delete_local_file,
    handle_list_directory,
    handle_move_or_rename_file,
    handle_read_file_metadata,
    handle_search_files_global,
)

__all__ = [
    "ALL_TOOL_NAMES",
    "TOOL_PARAMETER_SCHEMAS",
    "TOOL_HANDLERS",
    "handle_list_directory",
    "handle_read_file_metadata",
    "handle_search_files_global",
    "handle_move_or_rename_file",
    "handle_create_or_write_file",
    "handle_delete_local_file",
]
