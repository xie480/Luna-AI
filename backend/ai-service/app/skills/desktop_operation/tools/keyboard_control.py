"""
MCP 工具：键盘控制。

做什么：支持输入文本字符串、按下/释放单个按键、组合快捷键（如 Ctrl+C、Alt+Tab）。
风险等级：L1（低危，模拟用户输入有副作用，但通常不涉及数据修改）。
"""

from __future__ import annotations

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
        "action": {
            "type": "string",
            "enum": ["type_text", "press_key", "release_key", "hotkey"],
            "description": "键盘操作类型。",
        },
        "text": {
            "type": "string",
            "description": "要输入的文本字符串。action=type_text 时必填。",
            "maxLength": 10000,
        },
        "key": {
            "type": "string",
            "description": "按键名称（如 'enter'、'esc'、'a'、'f5'）。action=press_key/release_key 时必填。",
            "maxLength": 50,
        },
        "keys": {
            "type": "array",
            "items": {"type": "string", "maxLength": 50},
            "description": "组合键列表，如 ['ctrl', 'c'] 表示 Ctrl+C。action=hotkey 时必填。",
            "minItems": 2,
            "maxItems": 5,
        },
        "interval": {
            "type": "number",
            "description": "字符输入间隔（秒），默认 0.01。action=type_text 时有效。",
            "default": 0.01,
            "minimum": 0,
            "maximum": 1.0,
        },
        "press_duration": {
            "type": "number",
            "description": "按键按下持续时间（秒），默认 0.05。action=press_key 时有效。",
            "default": 0.05,
            "minimum": 0,
            "maximum": 5.0,
        },
    },
    "required": ["action"],
}


async def handle_keyboard_control(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    执行键盘控制操作。

    参数:
        parameters: 包含 action（必填）及各类操作对应参数的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(f"键盘控制请求 trace_id={trace_id} parameters={parameters}")

    action: str = parameters.get("action", "")
    text: str = parameters.get("text", "")
    key: str = parameters.get("key", "").strip().lower()
    keys: list[str] = parameters.get("keys", [])
    interval: float = parameters.get("interval", 0.01)
    press_duration: float = parameters.get("press_duration", 0.05)

    # 校验 action
    valid_actions = ("type_text", "press_key", "release_key", "hotkey")
    if action not in valid_actions:
        return build_error_result(
            "参数错误",
            f"不支持的键盘操作: {action}，有效值为 {valid_actions}",
        )

    # 校验参数完整性
    if action == "type_text" and not text:
        return build_error_result("参数错误", "type_text 操作必须提供 text 参数")
    if action in ("press_key", "release_key") and not key:
        return build_error_result("参数错误", f"{action} 操作必须提供 key 参数")
    if action == "hotkey" and len(keys) < 2:
        return build_error_result("参数错误", "hotkey 操作必须提供至少 2 个按键")

    # 执行操作
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
    except ImportError:
        logger.warning(f"键盘控制失败 trace_id={trace_id} 原因: pyautogui 库未安装")
        return build_error_result("依赖缺失", "pyautogui 库未安装，请执行 pip install pyautogui")

    try:
        if action == "type_text":
            # 输入文本（支持 Unicode，pyautogui 内部处理）
            pyautogui.typewrite(text, interval=interval) if all(ord(c) < 128 for c in text) else _type_unicode(text, interval)
            result_msg = f"已输入文本（{len(text)} 字符）"
            result_extra = {
                "文本长度": len(text),
                "输入间隔": f"{interval}s",
                "文本预览": text[:100] + ("..." if len(text) > 100 else ""),
            }

        elif action == "press_key":
            pyautogui.keyDown(key)
            time.sleep(press_duration)
            pyautogui.keyUp(key)
            result_msg = f"按键 '{key}' 已按下并释放"
            result_extra = {"按键": key, "按下时长": f"{press_duration}s"}

        elif action == "release_key":
            pyautogui.keyUp(key)
            result_msg = f"按键 '{key}' 已释放"
            result_extra = {"按键": key}

        elif action == "hotkey":
            # 组合键：先按下所有修饰键，再按下主键，最后逆序释放
            normalized_keys = [k.strip().lower() for k in keys]
            pyautogui.hotkey(*normalized_keys)
            keys_str = "+".join(normalized_keys)
            result_msg = f"组合键 {keys_str} 已触发"
            result_extra = {"组合键": keys_str, "按键数": len(normalized_keys)}

        else:
            return build_error_result("参数错误", f"未实现的键盘操作: {action}")

    except Exception as exc:
        logger.warning(f"键盘控制失败 trace_id={trace_id} action={action} 原因: {exc!s}")
        return build_error_result("系统错误", f"键盘操作执行失败: {exc!s}")

    logger.info(f"键盘控制成功 trace_id={trace_id} action={action}")
    return build_success_result(result_msg, result_extra)


def _type_unicode(text: str, interval: float) -> None:
    """
    输入包含 Unicode 字符的文本。

    做什么：pyautogui.typewrite 仅支持 ASCII，Unicode 文本需要逐字符处理。
    参数:
        text: 要输入的 Unicode 文本。
        interval: 字符间隔秒数。
    """
    import pyautogui

    for char in text:
        pyautogui.press(char)
        if interval > 0:
            time.sleep(interval)
