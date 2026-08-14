"""
MCP 工具：打开应用程序。

做什么：通过应用名称或可执行文件路径启动指定软件，支持传入启动参数，
         支持等待目标窗口出现后再返回。返回进程信息；
         对应用未找到、启动失败等情况进行错误处理。
为什么这样做：Windows 应用路径分散（PATH、注册表 App Paths、Program Files
             多级目录），且用户常用中文别名（如"微信"、"钉钉"）而非英文进程名。
             因此需要多级路径解析策略 + 中文别名映射表。
风险等级：L1（低危，启动进程有副作用，但通常不涉及数据修改）。
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
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
            "description": "应用程序名称（如 'notepad'、'chrome'、'微信'）或可执行文件的绝对路径。"
                           "传入名称时系统会依次尝试：绝对路径 → PATH → 注册表 App Paths → "
                           "中文别名表 → Program Files 深层搜索。",
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
        "wait_window_title": {
            "type": "string",
            "description": "可选。等待指定标题的窗口出现后再返回（仅 Windows）。"
                           "例如 '微信'、'WeChat'。超时后返回警告但不失败。",
            "maxLength": 256,
        },
        "wait_timeout": {
            "type": "number",
            "description": "等待窗口出现的超时秒数，默认 10.0。仅在 wait_window_title 非空时有效。",
            "default": 10.0,
            "minimum": 0.5,
            "maximum": 120.0,
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
                    working_directory（可选）、wait_for_start（可选）、
                    wait_window_title（可选）、wait_timeout（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本，成功时包含 PID 和进程信息。
    """
    logger.info(f"打开应用请求 trace_id={trace_id} parameters={parameters}")

    app_name: str = parameters.get("app_name", "").strip()
    arguments: list[str] = parameters.get("arguments", [])
    working_directory: str = parameters.get("working_directory", "").strip()
    wait_for_start: bool = parameters.get("wait_for_start", False)
    wait_window_title: str = parameters.get("wait_window_title", "").strip()
    wait_timeout: float = parameters.get("wait_timeout", 10.0)

    if not app_name:
        return build_error_result("参数错误", "应用程序名称不能为空")

    # 多级路径解析
    resolved_path, resolve_method = _resolve_app_path(app_name)
    if not resolved_path:
        logger.warning(f"打开应用失败 trace_id={trace_id} 原因: 应用未找到 app_name={app_name}")
        return build_error_result(
            "应用未找到",
            f"未找到应用程序: {app_name}",
            suggestion="请确认应用已安装，或提供可执行文件的绝对路径。"
                       "常见应用可使用中文别名（如'微信'、'钉钉'）或英文进程名（如'WeChat'、'DingTalk'）",
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

    # 等待窗口出现（可选）
    window_found = False
    if wait_window_title:
        window_found = _wait_for_window(wait_window_title, wait_timeout, trace_id)
        if not window_found:
            logger.warning(
                f"打开应用警告 trace_id={trace_id} 等待窗口超时 title={wait_window_title} "
                f"timeout={wait_timeout}s，进程仍在运行但窗口未出现"
            )

    result_extra: dict[str, Any] = {
        "进程PID": pid,
        "进程名": proc_name,
        "启动路径": resolved_path,
        "路径解析方式": resolve_method,
        "启动参数": " ".join(arguments) if arguments else "（无）",
    }
    if cwd:
        result_extra["工作目录"] = cwd
    if wait_window_title:
        result_extra["等待窗口"] = f"'{wait_window_title}' {'已出现' if window_found else '超时未出现'}"

    logger.info(f"打开应用成功 trace_id={trace_id} PID={pid} 应用={proc_name} 解析方式={resolve_method}")
    return build_success_result(f"应用程序已启动 (PID={pid})", result_extra)


# ============================================================
# 应用路径多级解析
# ============================================================

def _resolve_app_path(app_name: str) -> tuple[str | None, str]:
    """
    解析应用程序的可执行文件路径（多级策略）。

    做什么：按优先级依次尝试以下策略：
        1. 绝对路径直接使用
        2. 相对路径转绝对路径
        3. PATH 环境变量搜索
        4. Windows 注册表 App Paths 查询
        5. 中文别名映射表
        6. Program Files 深层目录搜索
    参数:
        app_name: 应用程序名称或路径。
    返回:
        tuple[str | None, str]: (解析后的绝对路径, 解析方式描述)。未找到时路径为 None。
    """
    # 策略 1：绝对路径直接使用
    if os.path.isabs(app_name) and os.path.isfile(app_name):
        return os.path.abspath(app_name), "绝对路径"

    # 策略 2：相对路径转绝对路径
    if os.path.isfile(app_name):
        return os.path.abspath(app_name), "相对路径"

    # 策略 3：PATH 环境变量搜索
    path_found = _search_in_path(app_name)
    if path_found:
        return path_found, "PATH 环境变量"

    # 策略 4：Windows 注册表 App Paths
    if platform.system() == "Windows":
        reg_found = _search_in_registry_app_paths(app_name)
        if reg_found:
            return reg_found, "注册表 App Paths"

    # 策略 5：中文别名映射表
    alias_found = _resolve_by_alias(app_name)
    if alias_found:
        return alias_found, "中文别名映射"

    # 策略 6：Program Files 深层目录搜索
    if platform.system() == "Windows":
        deep_found = _search_program_files_deep(app_name)
        if deep_found:
            return deep_found, "Program Files 深层搜索"

    return None, "未找到"


def _search_in_path(app_name: str) -> str | None:
    """在 PATH 环境变量中搜索可执行文件。"""
    path_env = os.environ.get("PATH", "")
    system = platform.system()

    for path_dir in path_env.split(os.pathsep):
        if not path_dir:
            continue

        extensions = [""]
        if system == "Windows":
            extensions = ["", ".exe", ".bat", ".cmd", ".com", ".msi"]

        for ext in extensions:
            candidate = os.path.join(path_dir, app_name + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return os.path.abspath(candidate)

    return None


def _search_in_registry_app_paths(app_name: str) -> str | None:
    """
    查询 Windows 注册表 App Paths 获取应用安装路径。

    做什么：读取 HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths
             和 HKEY_CURRENT_USER 下的对应键值。
    为什么这样做：很多应用（如微信、QQ、钉钉）安装时会注册 App Paths，
                 这是最可靠的官方路径查询方式。
    参数:
        app_name: 应用程序名称（不含扩展名）。
    返回:
        str | None: 找到的可执行文件绝对路径，未找到返回 None。
    """
    if platform.system() != "Windows":
        return None

    try:
        import winreg
    except ImportError:
        return None

    # 尝试匹配的名称变体（如 "wechat" → "WeChat.exe"、"WeChat"）
    name_variants = [
        app_name,
        app_name + ".exe",
        app_name.capitalize() + ".exe",
        app_name.upper() + ".exe",
    ]

    # 常见应用名 → 注册表键名映射（处理大小写和命名差异）
    registry_key_map = {
        "wechat": "WeChat.exe",
        "qq": "QQ.exe",
        "tim": "TIM.exe",
        "dingtalk": "DingTalk.exe",
        "钉钉": "DingTalk.exe",
        "微信": "WeChat.exe",
        "企业微信": "WXWork.exe",
        "wxwork": "WXWork.exe",
        "chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "mspaint": "mspaint.exe",
    }

    # 先查映射表
    lookup_name = registry_key_map.get(app_name.lower(), app_name)
    if lookup_name not in name_variants:
        name_variants.insert(0, lookup_name)

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]

    for hive, base_key_path in hives:
        for variant in name_variants:
            try:
                key_path = base_key_path + "\\" + variant
                with winreg.OpenKey(hive, key_path) as key:
                    # 默认值即为可执行文件完整路径
                    exe_path, _ = winreg.QueryValueEx(key, "")
                    if exe_path and os.path.isfile(exe_path):
                        return os.path.abspath(exe_path)
            except (OSError, FileNotFoundError):
                continue

    return None


def _resolve_by_alias(app_name: str) -> str | None:
    """
    通过中文别名映射表解析应用路径。

    做什么：将用户常用的中文应用名映射为英文进程名，
             再通过注册表或常见安装目录查找。
    为什么这样做：中国用户习惯说"打开微信"而非"打开 WeChat"，
                 需要别名表桥接语言差异。
    参数:
        app_name: 应用程序名称（可能是中文）。
    返回:
        str | None: 找到的可执行文件绝对路径，未找到返回 None。
    """
    # 中文别名 → (英文进程名, 常见安装目录提示)
    alias_map: dict[str, tuple[str, list[str]]] = {
        "微信": ("WeChat", [
            r"C:\Program Files (x86)\Tencent\WeChat",
            r"C:\Program Files\Tencent\WeChat",
        ]),
        "qq": ("QQ", [
            r"C:\Program Files (x86)\Tencent\QQ\Bin",
            r"C:\Program Files\Tencent\QQ\Bin",
        ]),
        "tim": ("TIM", [
            r"C:\Program Files (x86)\Tencent\TIM\Bin",
            r"C:\Program Files\Tencent\TIM\Bin",
        ]),
        "钉钉": ("DingTalk", [
            r"C:\Program Files (x86)\DingDing\main",
            r"C:\Program Files\DingDing\main",
            os.path.expandvars(r"%LOCALAPPDATA%\DingTalk"),
        ]),
        "企业微信": ("WXWork", [
            r"C:\Program Files (x86)\WXWork",
            r"C:\Program Files\WXWork",
        ]),
        "飞书": ("Feishu", [
            os.path.expandvars(r"%LOCALAPPDATA%\Feishu"),
        ]),
        "网易云音乐": ("cloudmusic", [
            r"C:\Program Files (x86)\Netease\CloudMusic",
            os.path.expandvars(r"%LOCALAPPDATA%\Netease\CloudMusic"),
        ]),
        "百度网盘": ("BaiduNetdisk", [
            r"C:\Program Files (x86)\Baidu\BaiduNetdisk",
            os.path.expandvars(r"%LOCALAPPDATA%\Baidu\BaiduNetdisk"),
        ]),
        "迅雷": ("Thunder", [
            r"C:\Program Files (x86)\Thunder Network\Thunder\Program",
        ]),
        "爱奇艺": ("QyPlayer", [
            r"C:\Program Files (x86)\IQIYI Video\LStyle",
        ]),
        "腾讯视频": ("QQLive", [
            r"C:\Program Files (x86)\Tencent\QQLive",
        ]),
        "优酷": ("Youku", [
            r"C:\Program Files (x86)\Youku",
        ]),
        "搜狗输入法": ("SogouInput", [
            r"C:\Program Files (x86)\SogouInput",
        ]),
        "有道词典": ("YoudaoDict", [
            r"C:\Program Files (x86)\Youdao\Dict",
        ]),
        "wps": ("wps", [
            r"C:\Program Files (x86)\Kingsoft\WPS Office",
            os.path.expandvars(r"%LOCALAPPDATA%\Kingsoft\WPS Office"),
        ]),
        "notepad++": ("notepad++", [
            r"C:\Program Files\Notepad++",
            r"C:\Program Files (x86)\Notepad++",
        ]),
    }

    lookup = app_name.lower().strip()
    if lookup not in alias_map:
        return None

    eng_name, search_dirs = alias_map[lookup]

    # 先通过注册表查找（最可靠）
    reg_result = _search_in_registry_app_paths(eng_name)
    if reg_result:
        return reg_result

    # 再在常见安装目录中搜索
    for search_dir in search_dirs:
        if not search_dir or not os.path.isdir(search_dir):
            continue
        found = _find_exe_in_dir(search_dir, eng_name)
        if found:
            return found

    return None


def _find_exe_in_dir(dir_path: str, exe_name: str) -> str | None:
    """
    在指定目录中递归查找可执行文件（最多 3 层深度）。

    参数:
        dir_path: 要搜索的目录。
        exe_name: 可执行文件名（不含扩展名）。
    返回:
        str | None: 找到的可执行文件绝对路径，未找到返回 None。
    """
    target_names = {
        exe_name.lower() + ".exe",
        exe_name.lower(),
        exe_name + ".exe",
        exe_name,
    }

    def _search(current_dir: str, depth: int) -> str | None:
        if depth > 3:
            return None
        try:
            for entry in os.listdir(current_dir):
                entry_path = os.path.join(current_dir, entry)
                if os.path.isfile(entry_path):
                    if entry.lower() in target_names:
                        return os.path.abspath(entry_path)
                elif os.path.isdir(entry_path) and depth < 3:
                    # 跳过明显的非安装目录
                    if entry.lower() in ("uninstall", "update", "crash", "temp", "log", "logs"):
                        continue
                    result = _search(entry_path, depth + 1)
                    if result:
                        return result
        except (OSError, PermissionError):
            pass
        return None

    return _search(dir_path, 0)


def _search_program_files_deep(app_name: str) -> str | None:
    """
    在 Program Files 目录中做深层搜索（最多 4 层）。

    做什么：作为兜底策略，在常见安装根目录下递归搜索匹配的可执行文件。
    为什么这样做：很多应用不注册 App Paths，也不在一级子目录，
                 需要更深层但有限制的搜索。
    参数:
        app_name: 应用程序名称（不含扩展名）。
    返回:
        str | None: 找到的可执行文件绝对路径，未找到返回 None。
    """
    search_roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]

    target_name = app_name.lower()
    extensions = (".exe", ".bat", ".cmd")

    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue

        def _search(current_dir: str, depth: int) -> str | None:
            if depth > 4:
                return None
            try:
                for entry in os.listdir(current_dir):
                    entry_path = os.path.join(current_dir, entry)
                    if os.path.isfile(entry_path):
                        name_lower = entry.lower()
                        # 匹配文件名（不含扩展名）或完整文件名
                        stem = os.path.splitext(name_lower)[0]
                        if stem == target_name or name_lower == target_name:
                            if name_lower.endswith(extensions):
                                return os.path.abspath(entry_path)
                    elif os.path.isdir(entry_path) and depth < 4:
                        # 跳过明显的非目标目录
                        skip_dirs = {
                            "uninstall", "update", "crash", "temp", "tmp",
                            "log", "logs", "cache", "backup", "old",
                            "windows", "microsoft", "common files",
                        }
                        if entry.lower() in skip_dirs:
                            continue
                        result = _search(entry_path, depth + 1)
                        if result:
                            return result
            except (OSError, PermissionError):
                pass
            return None

        found = _search(root, 0)
        if found:
            return found

    return None


# ============================================================
# 等待窗口出现
# ============================================================

def _wait_for_window(window_title: str, timeout: float, trace_id: str) -> bool:
    """
    等待指定标题的窗口出现（仅 Windows 有效）。

    做什么：轮询枚举当前所有顶层窗口，检查是否有窗口标题包含目标字符串。
    为什么这样做：GUI 应用启动后窗口渲染需要时间，直接操作鼠标容易点空。
    参数:
        window_title: 目标窗口标题（部分匹配，不区分大小写）。
        timeout: 最大等待秒数。
        trace_id: 全链路追踪 ID。
    返回:
        bool: 窗口在超时内出现返回 True，否则返回 False。
    """
    if platform.system() != "Windows":
        logger.warning(f"等待窗口仅在 Windows 平台有效，当前平台不支持 trace_id={trace_id}")
        return False

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        logger.warning(f"ctypes 不可用，无法等待窗口 trace_id={trace_id}")
        return False

    user32 = ctypes.windll.user32
    target_lower = window_title.lower()
    start_time = time.time()
    poll_interval = 0.3

    # 定义枚举窗口回调类型
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_callback(hwnd: int, lparam: int) -> bool:
        """枚举窗口回调：检查窗口标题是否匹配。"""
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value

        if target_lower in title.lower():
            return False  # 找到匹配，停止枚举

        return True  # 继续枚举

    callback = EnumWindowsProc(_enum_callback)

    while time.time() - start_time < timeout:
        found = not user32.EnumWindows(callback, 0)
        if found:
            elapsed = time.time() - start_time
            logger.info(
                f"等待窗口成功 trace_id={trace_id} title='{window_title}' "
                f"耗时={elapsed:.1f}s"
            )
            return True
        time.sleep(poll_interval)

    elapsed = time.time() - start_time
    logger.warning(
        f"等待窗口超时 trace_id={trace_id} title='{window_title}' "
        f"timeout={timeout}s 实际等待={elapsed:.1f}s"
    )
    return False
