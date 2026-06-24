"""
Local File Manager Skill 共享基座模块。

做什么：提供所有文件工具共享的常量定义、路径安全验证、格式化工具函数。
         所有工具文件均从此模块导入共享能力，避免重复代码。
为什么这样做：遵循单一职责原则，将跨工具共享的逻辑收敛到 base.py 中，
             每个工具文件只关注自身的 handler 逻辑。
"""

from __future__ import annotations

import os
import platform
import stat
from datetime import datetime, timezone
from typing import Any

from app.logger import logger


# ============================================================
# 工具名称常量（与技能注册 JSON 中的 tool.name 对应）
# ============================================================

TOOL_NAME_LIST_DIRECTORY: str = "list_directory"
TOOL_NAME_READ_METADATA: str = "read_file_metadata"
TOOL_NAME_SEARCH_FILES: str = "search_files_global"
TOOL_NAME_MOVE_RENAME: str = "move_or_rename_file"
TOOL_NAME_CREATE_WRITE: str = "create_or_write_file"
TOOL_NAME_DELETE_FILE: str = "delete_local_file"

# 工具统一名称列表，供外部遍历注册
ALL_TOOL_NAMES: list[str] = [
    TOOL_NAME_LIST_DIRECTORY,
    TOOL_NAME_READ_METADATA,
    TOOL_NAME_SEARCH_FILES,
    TOOL_NAME_MOVE_RENAME,
    TOOL_NAME_CREATE_WRITE,
    TOOL_NAME_DELETE_FILE,
]


# ============================================================
# 默认值常量
# ============================================================

# 搜索文件默认值
DEFAULT_SEARCH_TIMEOUT: float = 60.0          # 全局搜索超时秒数
DEFAULT_SEARCH_MAX_DEPTH: int = 8             # 全局搜索最大目录深度
DEFAULT_SEARCH_MAX_RESULTS: int = 200         # 全局搜索最大返回结果数
DEFAULT_FILE_WRITE_MAX_SIZE: int = 10 * 1024 * 1024   # 文件写入内容上限（10MB）


# ============================================================
# 排除的搜索目录列表
# ============================================================

_EXCLUDED_DIRS_WINDOWS: set[str] = {
    "System Volume Information",
    "$Recycle.Bin",
    "Windows",
    "ProgramData",
    "boot",
    "Config.Msi",
    "$WinREAgent",
    "Recovery",
    "System32",
    "System",
    "WinSxS",
    "AppData",
    "MSOCache",
    "PerfLogs",
}

_EXCLUDED_DIRS_UNIX: set[str] = {
    "System",
    "Library",
    ".Spotlight-V100",
    ".fseventsd",
    ".Trashes",
    ".TemporaryItems",
    "lost+found",
    ".git",
    "node_modules",
    "__pycache__",
    ".cache",
}

_EXCLUDED_DIRS_GENERIC: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".cache",
    ".Trash",
    "tmp",
    ".tmp",
    "Thumbs.db",
}


# ============================================================
# 操作系统保护区路径
# ============================================================

def _get_protected_path_prefixes() -> list[str]:
    """
    获取当前操作系统的受保护路径前缀列表。

    返回:
        list[str]: 受保护路径前缀列表（小写，便于不区分大小写比较）。
    """
    system = platform.system()
    protected: list[str] = []

    if system == "Windows":
        protected.extend([
            "c:\\windows",
            "c:\\windows\\system32",
            "c:\\windows\\system",
            "c:\\program files",
            "c:\\program files (x86)",
            "c:\\programdata",
            "c:\\system volume information",
            "c:\\$recycle.bin",
            "c:\\boot",
            "c:\\users\\default",
            "c:\\recovery",
        ])
        for drive_letter in "defghijklmnopqrstuvwxyz":
            protected.append(f"{drive_letter}:\\windows")

    return protected


_PROTECTED_PATH_PREFIXES: list[str] = _get_protected_path_prefixes()


# ============================================================
# 路径安全验证
# ============================================================


def is_protected_path(path: str) -> bool:
    """
    检查路径是否属于操作系统保护区。

    做什么：将给定路径转换为绝对路径后，与受保护路径前缀列表逐一匹配。
    参数:
        path: 要检查的文件或目录路径。
    返回:
        bool: 如果是受保护路径返回 True，否则返回 False。
    """
    try:
        abs_path = os.path.abspath(os.path.normpath(path))
    except (OSError, ValueError):
        return True

    system = platform.system()
    if system == "Windows":
        abs_path_lower = abs_path.lower()
        for prefix in _PROTECTED_PATH_PREFIXES:
            if abs_path_lower.startswith(prefix) or abs_path_lower == prefix.rstrip("\\"):
                return True
    else:
        for prefix in _PROTECTED_PATH_PREFIXES:
            if abs_path.startswith(prefix) or abs_path == prefix.rstrip("/"):
                return True

    return False


def validate_path_safety(path: str, allow_nonexistent: bool = False) -> str:
    """
    验证路径安全性。

    做什么：执行三级安全校验：
            1. 检查路径不为空。
            2. 检查路径无路径穿越风险。
            3. 检查路径不在操作系统保护区内。
            4. 如果 allow_nonexistent=False，检查路径是否存在。
    参数:
        path: 要验证的目标路径。
        allow_nonexistent: 是否允许路径不存在。默认为 False。
    返回:
        str: 验证通过后的标准化绝对路径。
    抛出:
        ValueError: 如果路径不合法、受保护或不存在。
    """
    if not path or not path.strip():
        raise ValueError("路径不能为空")

    path_stripped = path.strip()
    try:
        norm_path = os.path.normpath(path_stripped)
        abs_path = os.path.abspath(norm_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"路径格式非法: {exc!s}") from exc

    # 检查路径穿越：统一将正斜杠替换为 os.sep 后拆分，
    # 防止用户用 "C:/Users/../Windows" 绕过 os.sep（反斜杠）拆分检测。
    normalized_for_check = path_stripped.replace("/", os.sep)
    if ".." in normalized_for_check.split(os.sep):
        raise ValueError("路径包含非法穿越符（..），已拒绝操作")

    if is_protected_path(abs_path):
        raise ValueError(f"路径位于操作系统保护区，已拒绝操作: {abs_path}")

    if not allow_nonexistent and not os.path.exists(abs_path):
        raise ValueError(f"路径不存在: {abs_path}")

    return abs_path


def get_excluded_dirs() -> set[str]:
    """
    获取当前操作系统的搜索排除目录集合。

    返回:
        set[str]: 排除目录名称集合。
    """
    system = platform.system()
    if system == "Windows":
        excluded = _EXCLUDED_DIRS_WINDOWS.copy()
    elif system == "Darwin":
        excluded = _EXCLUDED_DIRS_UNIX.copy()
    else:
        excluded: set[str] = set()
    excluded.update(_EXCLUDED_DIRS_GENERIC)
    return excluded


# ============================================================
# 格式化工具函数
# ============================================================


def format_file_size(size: int) -> str:
    """
    将字节数格式化为人类可读的文件大小字符串。

    参数:
        size: 文件字节数。
    返回:
        str: 格式化后的大小字符串（如 "1.23 MB"）。
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.2f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.2f} PB"


def format_timestamp(timestamp: float) -> str:
    """
    将时间戳格式化为可读的日期时间字符串。

    参数:
        timestamp: Unix 时间戳（秒）。
    返回:
        str: 格式化后的日期时间字符串（如 "2024-01-15 14:30:00 UTC"）。
    """
    try:
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OSError, ValueError, OverflowError):
        return "（时间戳无效）"


def get_drive_type(drive_path: str) -> str:
    """
    获取 Windows 盘符类型。

    参数:
        drive_path: 盘符路径，如 "C:\\"。
    返回:
        str: 驱动器类型描述（fixed, removable, remote, cdrom, ram, unknown）。
    """
    import ctypes

    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
    type_map = {
        0: "unknown",
        1: "no_root",
        2: "removable",
        3: "fixed",
        4: "remote",
        5: "cdrom",
        6: "ram",
    }
    return type_map.get(drive_type, "unknown")


def remove_readonly(filepath: str) -> None:
    """
    移除文件的只读属性（如果存在）。

    参数:
        filepath: 目标文件路径。
    """
    try:
        current_mode = os.stat(filepath).st_mode
        if not current_mode & stat.S_IWRITE:
            os.chmod(filepath, current_mode | stat.S_IWRITE)
    except OSError:
        pass


def make_writable(dirpath: str) -> None:
    """
    递归设置目录及其下所有内容为可写。

    参数:
        dirpath: 目标目录路径。
    """
    try:
        for root, dirs, files in os.walk(dirpath, topdown=False):
            for name in files:
                try:
                    remove_readonly(os.path.join(root, name))
                except OSError:
                    continue
            for name in dirs:
                try:
                    dir_path = os.path.join(root, name)
                    current_mode = os.stat(dir_path).st_mode
                    if not current_mode & stat.S_IWRITE:
                        os.chmod(dir_path, current_mode | stat.S_IWRITE)
                except OSError:
                    continue
    except OSError:
        pass


# ============================================================
# 工具 Handler 签名类型（仅用于类型标注，不做运行时依赖）
# ============================================================

# 每个工具 handler 的函数签名: (parameters: dict[str, Any], trace_id: str) -> str
ToolHandler = Any  # 实际类型: Callable[[dict[str, Any], str], Awaitable[str]]
