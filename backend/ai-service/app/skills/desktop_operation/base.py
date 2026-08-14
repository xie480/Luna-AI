"""
Desktop Operation Skill 共享基座模块。

做什么：提供所有桌面操作工具共享的常量定义、屏幕信息查询、DPI 感知、
         坐标校验、统一返回格式构建等公共能力。
         所有工具文件均从此模块导入共享能力，避免重复代码。
为什么这样做：遵循单一职责原则，将跨工具共享的逻辑收敛到 base.py 中，
             每个工具文件只关注自身的 handler 逻辑。
"""

from __future__ import annotations

import base64
import io
import os
import platform
import subprocess
import time
from typing import Any

from app.logger import logger

# ============================================================
# 工具名称常量（与技能注册 JSON 中的 tool.name 对应）
# ============================================================

TOOL_NAME_SCREENSHOT: str = "screenshot"
TOOL_NAME_OPEN_APPLICATION: str = "open_application"
TOOL_NAME_MOUSE_CONTROL: str = "mouse_control"
TOOL_NAME_KEYBOARD_CONTROL: str = "keyboard_control"
TOOL_NAME_CLOSE_APPLICATION: str = "close_application"

# 工具统一名称列表，供外部遍历注册
ALL_TOOL_NAMES: list[str] = [
    TOOL_NAME_SCREENSHOT,
    TOOL_NAME_OPEN_APPLICATION,
    TOOL_NAME_MOUSE_CONTROL,
    TOOL_NAME_KEYBOARD_CONTROL,
    TOOL_NAME_CLOSE_APPLICATION,
]


# ============================================================
# 默认值常量
# ============================================================

DEFAULT_SCREENSHOT_FORMAT: str = "png"          # 截图默认输出格式
DEFAULT_CLOSE_TIMEOUT: float = 5.0              # 优雅关闭默认等待秒数
DEFAULT_MOUSE_MOVE_DURATION: float = 0.1        # 鼠标移动默认动画时长（秒）
DEFAULT_SCROLL_STEPS: int = 3                   # 滚轮默认滚动步数


# ============================================================
# 统一返回格式
# ============================================================

def build_success_result(data: str, extra: dict[str, Any] | None = None) -> str:
    """
    构建工具执行成功的统一返回格式。

    参数:
        data: 主要结果文本。
        extra: 可选的附加键值对，会追加到返回文本中。
    返回:
        str: 格式化后的成功结果文本。
    """
    parts = [f"【操作成功】{data}"]
    if extra:
        for key, value in extra.items():
            parts.append(f"  {key}: {value}")
    return "\n".join(parts)


def build_error_result(error_type: str, message: str, suggestion: str = "") -> str:
    """
    构建工具执行失败的统一返回格式。

    参数:
        error_type: 错误类型标识（如 "参数错误"、"权限错误"、"系统错误"）。
        message: 错误详情。
        suggestion: 可选的修复建议。
    返回:
        str: 格式化后的错误结果文本。
    """
    parts = [f"【{error_type}】{message}"]
    if suggestion:
        parts.append(f"  建议: {suggestion}")
    return "\n".join(parts)


# ============================================================
# DPI 与屏幕信息
# ============================================================

def get_screen_info() -> dict[str, Any]:
    """
    获取当前屏幕信息（分辨率、DPI 缩放比例、屏幕数量）。

    返回:
        dict: 包含 screen_count、screens 列表（每项含 width/height/left/top/is_primary）、
              dpi_scale（主屏缩放比例）的字典。
    异常:
        RuntimeError: 无法获取屏幕信息时抛出。
    """
    system = platform.system()

    if system == "Windows":
        return _get_screen_info_windows()
    elif system == "Darwin":
        return _get_screen_info_macos()
    else:
        return _get_screen_info_linux()


def _get_screen_info_windows() -> dict[str, Any]:
    """Windows 平台屏幕信息获取（支持 DPI 感知）。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 设置 DPI 感知，确保获取物理像素坐标
    try:
        # Windows 8.1+ 使用 SetProcessDpiAwareness
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (OSError, AttributeError):
        try:
            user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass

    # 获取主屏分辨率（物理像素）
    width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
    height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

    # 获取虚拟屏幕尺寸（多屏总区域）
    virtual_width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    virtual_height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    virtual_left = user32.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
    virtual_top = user32.GetSystemMetrics(77)     # SM_YVIRTUALSCREEN

    # 获取主屏 DPI 缩放
    hdc = user32.GetDC(0)
    dpi_x = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
    dpi_y = gdi32.GetDeviceCaps(hdc, 90)  # LOGPIXELSY
    user32.ReleaseDC(0, hdc)
    dpi_scale = dpi_x / 96.0

    screens = [{
        "index": 0,
        "left": 0,
        "top": 0,
        "width": width,
        "height": height,
        "is_primary": True,
    }]

    # 如果虚拟屏幕大于主屏，说明有多屏
    if virtual_width > width or virtual_height > height:
        screens.append({
            "index": 1,
            "left": virtual_left,
            "top": virtual_top,
            "width": virtual_width,
            "height": virtual_height,
            "is_primary": False,
        })

    return {
        "screen_count": len(screens),
        "screens": screens,
        "dpi_scale": dpi_scale,
        "virtual_left": virtual_left,
        "virtual_top": virtual_top,
        "virtual_width": virtual_width,
        "virtual_height": virtual_height,
    }


def _get_screen_info_macos() -> dict[str, Any]:
    """macOS 平台屏幕信息获取。"""
    try:
        import AppKit
        screens = []
        for i, screen in enumerate(AppKit.NSScreen.screens()):
            frame = screen.frame()
            screens.append({
                "index": i,
                "left": int(frame.origin.x),
                "top": int(frame.origin.y),
                "width": int(frame.size.width),
                "height": int(frame.size.height),
                "is_primary": i == 0,
            })
        return {
            "screen_count": len(screens),
            "screens": screens,
            "dpi_scale": 2.0 if AppKit.NSScreen.mainScreen().backingScaleFactor() == 2.0 else 1.0,
        }
    except ImportError:
        # 降级：通过 Quartz 获取
        import Quartz
        main_id = Quartz.CGMainDisplayID()
        width = Quartz.CGDisplayPixelsWide(main_id)
        height = Quartz.CGDisplayPixelsHigh(main_id)
        return {
            "screen_count": 1,
            "screens": [{"index": 0, "left": 0, "top": 0, "width": width, "height": height, "is_primary": True}],
            "dpi_scale": 1.0,
        }


def _get_screen_info_linux() -> dict[str, Any]:
    """Linux 平台屏幕信息获取。"""
    try:
        import pyautogui
        size = pyautogui.size()
        return {
            "screen_count": 1,
            "screens": [{"index": 0, "left": 0, "top": 0, "width": size.width, "height": size.height, "is_primary": True}],
            "dpi_scale": 1.0,
        }
    except Exception as exc:
        raise RuntimeError(f"无法获取屏幕信息: {exc!s}") from exc


# ============================================================
# 坐标校验
# ============================================================

def validate_coordinates(x: int, y: int, screen_index: int = 0) -> tuple[bool, str]:
    """
    校验坐标是否在屏幕有效范围内。

    参数:
        x: 目标 X 坐标。
        y: 目标 Y 坐标。
        screen_index: 目标屏幕索引（多屏场景）。
    返回:
        tuple[bool, str]: (是否合法, 错误信息)。合法时错误信息为空字符串。
    """
    try:
        info = get_screen_info()
    except RuntimeError:
        # 无法获取屏幕信息时，仅做基本校验
        if x < 0 or y < 0:
            return False, f"坐标越界: ({x}, {y})，坐标值不能为负数"
        return True, ""

    screens = info.get("screens", [])
    if not screens:
        return False, "未检测到可用屏幕"

    # 使用虚拟屏幕范围（多屏场景）
    virtual_left = info.get("virtual_left", 0)
    virtual_top = info.get("virtual_top", 0)
    virtual_width = info.get("virtual_width", screens[0]["width"])
    virtual_height = info.get("virtual_height", screens[0]["height"])

    virtual_right = virtual_left + virtual_width
    virtual_bottom = virtual_top + virtual_height

    if not (virtual_left <= x < virtual_right and virtual_top <= y < virtual_bottom):
        return False, (
            f"坐标越界: ({x}, {y})，有效范围为 "
            f"X=[{virtual_left}, {virtual_right}), Y=[{virtual_top}, {virtual_bottom})"
        )

    return True, ""


def validate_region(
    left: int, top: int, width: int, height: int, screen_index: int = 0
) -> tuple[bool, str]:
    """
    校验截图区域是否在屏幕有效范围内。

    参数:
        left: 区域左上角 X 坐标。
        top: 区域左上角 Y 坐标。
        width: 区域宽度。
        height: 区域高度。
        screen_index: 目标屏幕索引。
    返回:
        tuple[bool, str]: (是否合法, 错误信息)。
    """
    if width <= 0 or height <= 0:
        return False, f"区域尺寸非法: width={width}, height={height}，宽度和高度必须为正数"

    valid, msg = validate_coordinates(left, top, screen_index)
    if not valid:
        return False, msg

    valid, msg = validate_coordinates(left + width - 1, top + height - 1, screen_index)
    if not valid:
        return False, f"区域右下角越界: {msg}"

    return True, ""


# ============================================================
# 图像编码工具
# ============================================================

def image_to_base64(image_bytes: bytes, fmt: str = "png") -> str:
    """
    将图像字节数据编码为 base64 字符串。

    参数:
        image_bytes: 图像原始字节数据。
        fmt: 图像格式标识（png/jpeg），仅用于日志标识。
    返回:
        str: base64 编码字符串。
    """
    return base64.b64encode(image_bytes).decode("ascii")


def save_image_to_file(image_bytes: bytes, filepath: str) -> str:
    """
    将图像字节数据保存为文件。

    参数:
        image_bytes: 图像原始字节数据。
        filepath: 目标文件绝对路径。
    返回:
        str: 保存成功的文件绝对路径。
    异常:
        OSError: 文件写入失败时抛出。
    """
    # 确保目标目录存在
    dir_path = os.path.dirname(filepath)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    return os.path.abspath(filepath)


# ============================================================
# 进程操作工具
# ============================================================

def find_process_by_name(process_name: str) -> list[dict[str, Any]]:
    """
    通过进程名查找匹配的进程列表。

    参数:
        process_name: 进程名称（不含路径，如 "notepad.exe" 或 "chrome"）。
    返回:
        list[dict]: 匹配的进程信息列表，每项含 pid、name、exe、status。
    """
    import psutil

    matched: list[dict[str, Any]] = []
    search_name = process_name.lower().strip()

    for proc in psutil.process_iter(["pid", "name", "exe", "status"]):
        try:
            pinfo = proc.info
            proc_name = (pinfo.get("name") or "").lower()
            proc_exe = (pinfo.get("exe") or "").lower()

            # 匹配进程名或可执行文件名
            if search_name in proc_name or search_name in os.path.basename(proc_exe):
                matched.append({
                    "pid": pinfo["pid"],
                    "name": pinfo.get("name", ""),
                    "exe": pinfo.get("exe", ""),
                    "status": pinfo.get("status", ""),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return matched


def find_process_by_pid(pid: int) -> dict[str, Any] | None:
    """
    通过 PID 查找进程信息。

    参数:
        pid: 进程 ID。
    返回:
        dict | None: 找到时返回进程信息字典，未找到返回 None。
    """
    import psutil

    try:
        proc = psutil.Process(pid)
        return {
            "pid": proc.pid,
            "name": proc.name(),
            "exe": proc.exe(),
            "status": proc.status(),
        }
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied:
        return {
            "pid": pid,
            "name": "（权限不足）",
            "exe": "",
            "status": "access_denied",
        }


def terminate_process_graceful(pid: int, timeout: float = DEFAULT_CLOSE_TIMEOUT) -> tuple[bool, str]:
    """
    尝试优雅终止进程（发送关闭信号）。

    参数:
        pid: 目标进程 ID。
        timeout: 等待进程退出的超时秒数。
    返回:
        tuple[bool, str]: (是否成功, 结果描述)。
    """
    import psutil

    try:
        proc = psutil.Process(pid)
        proc.terminate()  # 发送 SIGTERM（Windows 上为 WM_CLOSE）

        try:
            proc.wait(timeout=timeout)
            return True, f"进程 (PID={pid}) 已在 {timeout}s 内优雅退出"
        except psutil.TimeoutExpired:
            return False, f"进程 (PID={pid}) 在 {timeout}s 内未响应关闭信号"

    except psutil.NoSuchProcess:
        return False, f"进程不存在: PID={pid}"
    except psutil.AccessDenied:
        return False, f"权限不足，无法终止进程: PID={pid}"
    except Exception as exc:
        return False, f"终止进程时发生异常: {exc!s}"


def terminate_process_force(pid: int) -> tuple[bool, str]:
    """
    强制终止进程（SIGKILL / TerminateProcess）。

    参数:
        pid: 目标进程 ID。
    返回:
        tuple[bool, str]: (是否成功, 结果描述)。
    """
    import psutil

    try:
        proc = psutil.Process(pid)
        proc.kill()  # 强制终止
        proc.wait(timeout=3.0)
        return True, f"进程 (PID={pid}) 已被强制终止"
    except psutil.NoSuchProcess:
        return False, f"进程不存在: PID={pid}"
    except psutil.AccessDenied:
        return False, f"权限不足，无法强制终止进程: PID={pid}"
    except psutil.TimeoutExpired:
        return False, f"进程 (PID={pid}) 强制终止后未在预期时间内退出"
    except Exception as exc:
        return False, f"强制终止进程时发生异常: {exc!s}"


# ============================================================
# 工具 Handler 签名类型（仅用于类型标注，不做运行时依赖）
# ============================================================

# 每个工具 handler 的函数签名: (parameters: dict[str, Any], trace_id: str) -> str
ToolHandler = Any  # 实际类型: Callable[[dict[str, Any], str], Awaitable[str]]
