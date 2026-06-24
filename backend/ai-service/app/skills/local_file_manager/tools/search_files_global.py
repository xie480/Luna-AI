"""
MCP 工具：全局文件搜索。

做什么：根据文件名模式在指定盘符或常用目录下递归搜索匹配的文件。
        支持集成 Everything SDK 进行极速搜索，不支持时自动回退至高性能扫描。
风险等级：L0（低危，只读探测，不需要前端 Gating 确认）。
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import fnmatch
import os
import platform
from typing import Any

from app.logger import logger
from app.skills.local_file_manager.base import (
    DEFAULT_SEARCH_MAX_DEPTH,
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    format_file_size,
    format_timestamp,
    get_drive_type,
    get_excluded_dirs,
    is_protected_path,
)

# ============================================================
# Everything SDK 绑定 (Tier 1)
# ============================================================
EVERYTHING_DLL_PATH = r"D:\Everything-SDK\dll\Everything64.dll"

EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
EVERYTHING_REQUEST_SIZE = 0x00000010
EVERYTHING_REQUEST_DATE_MODIFIED = 0x00000040

everything_dll = None

# Everything IPC 窗口类名，用于检测 Everything 搜索服务是否正在运行
_EVERYTHING_IPC_WINDOW_CLASS = "EVERYTHING_TASKBAR_NOTIFICATION"


def _check_everything_service_running() -> bool:
    """
    通过 Windows API 检测 Everything 搜索服务是否正在运行。

    Everything SDK 通过 IPC（窗口消息）与 Everything.exe 进程通信。
    如果 Everything.exe 未启动，DLL 可以加载成功但所有查询将返回 0 结果。
    本函数通过查找 Everything 的 IPC 通知窗口判断服务状态。

    返回:
        bool: Everything 服务正在运行返回 True，否则返回 False。
    """
    try:
        hwnd = ctypes.windll.user32.FindWindowW(_EVERYTHING_IPC_WINDOW_CLASS, None)
        return hwnd != 0
    except Exception:
        return False


if platform.system() == "Windows":
    try:
        everything_dll = ctypes.WinDLL(EVERYTHING_DLL_PATH)
        everything_dll.Everything_SetSearchW.argtypes = [ctypes.wintypes.LPCWSTR]
        everything_dll.Everything_SetRequestFlags.argtypes = [ctypes.wintypes.DWORD]
        everything_dll.Everything_SetMax.argtypes = [ctypes.wintypes.DWORD]
        everything_dll.Everything_QueryW.argtypes = [ctypes.wintypes.BOOL]
        everything_dll.Everything_QueryW.restype = ctypes.wintypes.BOOL
        everything_dll.Everything_GetNumResults.restype = ctypes.wintypes.DWORD
        everything_dll.Everything_GetResultFullPathNameW.argtypes = [
            ctypes.wintypes.DWORD, ctypes.wintypes.LPWSTR, ctypes.wintypes.DWORD
        ]
        everything_dll.Everything_GetResultSize.argtypes = [
            ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.c_uint64)
        ]
        everything_dll.Everything_GetResultDateModified.argtypes = [
            ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.c_uint64)
        ]

        # DLL 加载成功后，检测 Everything 搜索服务是否正在运行
        if _check_everything_service_running():
            logger.info("Everything SDK 动态库加载成功，搜索服务运行中。")
        else:
            # 服务未运行时禁用 SDK，直接回退到 scandir 引擎
            # 避免无意义的 SDK 调用（QueryW 会静默返回 0 结果）
            logger.warning(
                "Everything SDK 动态库加载成功，但 Everything 搜索服务未运行，"
                "将回退为内置 scandir 引擎。请启动 Everything.exe 以启用极速搜索。"
            )
            everything_dll = None
    except Exception as e:
        logger.warning(f"Everything SDK 加载失败，将回退为内置搜索: {e}")
        everything_dll = None


# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "文件匹配模式，支持通配符。例如：'*.txt', 'report_*.pdf', '精确文件名.docx'。",
            "minLength": 1,
            "maxLength": 500,
        },
        "drive": {
            "type": "string",
            "description": "指定盘符（如 'C:', 'D:'）。如果不确定请留空，系统将自动搜索所有可用盘符。",
            "default": "",
            "maxLength": 10,
        },
    },
    "required": ["pattern"],
}


async def handle_search_files_global(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    全局搜索文件入口。
    """
    logger.info(
        f"全局文件搜索请求 trace_id={trace_id} parameters={parameters}"
    )

    pattern: str = parameters.get("pattern", "")
    drive: str = parameters.get("drive", "")

    if not pattern or not pattern.strip():
        return "【搜索参数错误】搜索模式（pattern）不能为空。"
    pattern = pattern.strip()

    search_roots = _resolve_search_roots(drive)
    excluded_dirs = get_excluded_dirs()
    search_results: list[dict[str, Any]] = []
    engine_name = "未知"

    try:
        if everything_dll:
            # 优先使用 Everything 极速引擎
            logger.info(f"使用 Everything 极速引擎 trace_id={trace_id}")
            engine_name = "Everything 极速引擎"
            search_results = await asyncio.wait_for(
                asyncio.to_thread(_search_everything_sync, pattern, DEFAULT_SEARCH_MAX_RESULTS, drive),
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )

            # Everything 返回空结果时自动降级到 scandir 引擎
            # 原因：Everything 服务可能在模块加载后被用户关闭，
            #       _search_everything_sync 检测到服务不可用时返回空列表
            if not search_results:
                logger.warning(
                    f"Everything 引擎返回空结果，自动降级到 scandir 引擎 "
                    f"trace_id={trace_id} pattern={pattern}"
                )
                engine_name = "scandir 内置引擎（Everything 降级）"
                search_results = await asyncio.wait_for(
                    asyncio.to_thread(
                        _scandir_fallback_sync,
                        search_roots=search_roots,
                        pattern=pattern,
                        excluded_dirs=excluded_dirs,
                        max_depth=DEFAULT_SEARCH_MAX_DEPTH,
                        max_results=DEFAULT_SEARCH_MAX_RESULTS,
                    ),
                    timeout=DEFAULT_SEARCH_TIMEOUT,
                )
        else:
            # Everything 不可用，直接使用 scandir 引擎
            logger.info(f"使用 scandir 内置引擎 trace_id={trace_id}")
            engine_name = "scandir 内置引擎"
            search_results = await asyncio.wait_for(
                asyncio.to_thread(
                    _scandir_fallback_sync,
                    search_roots=search_roots,
                    pattern=pattern,
                    excluded_dirs=excluded_dirs,
                    max_depth=DEFAULT_SEARCH_MAX_DEPTH,
                    max_results=DEFAULT_SEARCH_MAX_RESULTS,
                ),
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )
    except asyncio.TimeoutError:
        logger.warning(f"文件搜索超时 trace_id={trace_id} pattern={pattern}")
        return _format_search_results(pattern, search_results, search_roots, engine_name, timed_out=True)

    logger.info(
        f"文件搜索完成 trace_id={trace_id} count={len(search_results)} engine={engine_name}"
    )
    return _format_search_results(pattern, search_results, search_roots, engine_name, timed_out=False)


# ============================================================
# 核心搜索实现
# ============================================================

def _search_everything_sync(pattern: str, max_results: int, drive: str) -> list[dict[str, Any]]:
    """Tier 1: 调用 Everything SDK 的同步核心逻辑"""
    if not everything_dll:
        return []

    # 运行时再次检测 Everything 服务是否仍然在运行
    # 服务可能在模块加载后被用户关闭，此时需要降级而非返回空结果
    if not _check_everything_service_running():
        logger.warning("Everything 搜索服务已停止运行，本次搜索将使用降级引擎。")
        return []

    # 组装 Everything 查询语法
    # Everything SDK 搜索语法要求盘符后必须带反斜杠，如 "E:\ *.py"
    search_query = pattern
    if drive:
        drive_letter = drive.rstrip("\\/").upper()
        if not drive_letter.endswith(":"):
            drive_letter += ":"
        # 盘符后必须保留反斜杠，Everything SDK 以此区分盘符过滤与普通文本
        drive_prefix = f"{drive_letter}\\"
        search_query = f"{drive_prefix} {pattern}"

    logger.debug(f"Everything 查询语句: {search_query}")
    everything_dll.Everything_SetSearchW(search_query)
    everything_dll.Everything_SetRequestFlags(
        EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME |
        EVERYTHING_REQUEST_SIZE |
        EVERYTHING_REQUEST_DATE_MODIFIED
    )
    everything_dll.Everything_SetMax(max_results)

    # 阻塞查询（通常耗时极短，依赖外部服务）
    query_ok = everything_dll.Everything_QueryW(True)
    if not query_ok:
        logger.warning(
            f"Everything QueryW 调用失败（返回 False），"
            f"搜索语句: {search_query}，服务可能已断开连接。"
        )
        return []

    num_results = everything_dll.Everything_GetNumResults()
    results = []

    path_buf = ctypes.create_unicode_buffer(32768)
    size_buf = ctypes.c_uint64(0)
    ft_buf = ctypes.c_uint64(0)

    for i in range(num_results):
        everything_dll.Everything_GetResultFullPathNameW(i, path_buf, 32768)
        everything_dll.Everything_GetResultSize(i, ctypes.byref(size_buf))
        everything_dll.Everything_GetResultDateModified(i, ctypes.byref(ft_buf))

        full_path = path_buf.value
        ft_val = ft_buf.value

        # FILETIME 转 UNIX Timestamp
        # 116444736000000000 是 1601年 到 1970年 的 100ns 周期数
        if ft_val > 116444736000000000:
            modified_ts = (ft_val - 116444736000000000) / 10000000.0
        else:
            modified_ts = 0

        results.append({
            "path": full_path,
            "name": os.path.basename(full_path),
            "size": size_buf.value,
            "modified": modified_ts,
        })

    return results


def _scandir_fallback_sync(
    search_roots: list[str],
    pattern: str,
    excluded_dirs: set[str],
    max_depth: int,
    max_results: int,
) -> list[dict[str, Any]]:
    """Tier 2: 纯 Python 基于 os.scandir 的降级同步搜索"""
    results: list[dict[str, Any]] = []
    excluded_lower: set[str] = {d.lower() for d in excluded_dirs}

    for root in search_roots:
        if not os.path.isdir(root):
            continue

        stack = [(root, 0)]  # LIFO 栈避免递归深度溢出 (path, depth)

        while stack and len(results) < max_results:
            current_path, depth = stack.pop()
            if depth > max_depth or is_protected_path(current_path):
                continue

            try:
                with os.scandir(current_path) as entries:
                    for entry in entries:
                        if entry.name.lower() in excluded_lower:
                            continue

                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append((entry.path, depth + 1))
                            elif entry.is_file(follow_symlinks=False) and fnmatch.fnmatch(entry.name, pattern):
                                stat = entry.stat()
                                results.append({
                                    "path": entry.path,
                                    "name": entry.name,
                                    "size": stat.st_size,
                                    "modified": stat.st_mtime,
                                })
                                if len(results) >= max_results:
                                    return results
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

    return results


# ============================================================
# 辅助格式化函数
# ============================================================

def _resolve_search_roots(drive: str) -> list[str]:
    roots: list[str] = []
    system = platform.system()

    if drive and drive.strip():
        drive = drive.strip().rstrip("\\/")
        if not drive.endswith(":"):
            drive = drive + ":"
        roots.append(f"{drive}\\" if system == "Windows" else "/")
        return roots

    if system == "Windows":
        for letter in "cdefghijklmnopqrstuvwxyz":
            potential = f"{letter}:\\"
            if os.path.exists(potential):
                try:
                    if get_drive_type(potential) in ("fixed", "ram"):
                        roots.append(potential)
                except Exception:
                    roots.append(potential)
        if not roots:
            roots.append("C:\\")
    else:
        roots.append(os.path.expanduser("~"))

    return roots


def _format_search_results(
    pattern: str,
    results: list[dict[str, Any]],
    roots: list[str],
    engine_name: str,
    timed_out: bool,
) -> str:
    output_parts: list[str] = []
    roots_str = ", ".join(roots)

    if timed_out:
        output_parts.append(f"⚠️ 搜索超时，返回部分结果（最大上限 {DEFAULT_SEARCH_MAX_RESULTS} 条）")
    else:
        output_parts.append("🔍 文件搜索完成")

    output_parts.append(f"   使用的引擎: {engine_name}")
    output_parts.append(f"   搜索模式: {pattern}")
    if engine_name != "Everything 极速引擎":
        output_parts.append(f"   搜索范围: {roots_str}")
    output_parts.append("")

    if not results:
        output_parts.append("未找到匹配的文件。")
        return "\n".join(output_parts)

    output_parts.append(f"共找到 {len(results)} 个匹配的文件：")
    output_parts.append("")

    results_sorted = sorted(results, key=lambda x: x["path"].lower())
    for idx, r in enumerate(results_sorted, 1):
        output_parts.append(f"{idx}. {r['name']}")
        output_parts.append(f"   路径: {r['path']}")
        output_parts.append(f"   大小: {format_file_size(r['size'])}")
        output_parts.append(f"   修改时间: {format_timestamp(r['modified'])}")
        output_parts.append("")

    output_text = "\n".join(output_parts)
    if len(output_text) > 20000:
        output_text = output_text[:20000] + "\n\n...（结果过长已截断）"

    return output_text
