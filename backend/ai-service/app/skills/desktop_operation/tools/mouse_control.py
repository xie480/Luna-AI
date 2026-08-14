"""
MCP 工具：鼠标控制。

做什么：支持移动鼠标到指定坐标、单击/双击（左键、右键、中键）、
         拖拽（从起点到终点）、滚轮滚动（指定方向与步数）。
风险等级：L1（低危，模拟用户输入有副作用，但通常不涉及数据修改）。
"""

from __future__ import annotations

import time
from typing import Any

from app.logger import logger
from app.skills.desktop_operation.base import (
    DEFAULT_MOUSE_MOVE_DURATION,
    DEFAULT_SCROLL_STEPS,
    build_error_result,
    build_success_result,
    get_screen_info,
    validate_coordinates,
)

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["move", "click", "double_click", "drag", "scroll"],
            "description": "鼠标操作类型。",
        },
        "x": {
            "type": "integer",
            "description": "目标 X 坐标（像素）。move/click/double_click 必填，drag 为起点 X。",
        },
        "y": {
            "type": "integer",
            "description": "目标 Y 坐标（像素）。move/click/double_click 必填，drag 为起点 Y。",
        },
        "button": {
            "type": "string",
            "enum": ["left", "right", "middle"],
            "description": "鼠标按键，默认 left。click/double_click 有效。",
            "default": "left",
        },
        "end_x": {
            "type": "integer",
            "description": "拖拽终点 X 坐标。action=drag 时必填。",
        },
        "end_y": {
            "type": "integer",
            "description": "拖拽终点 Y 坐标。action=drag 时必填。",
        },
        "scroll_direction": {
            "type": "string",
            "enum": ["up", "down"],
            "description": "滚轮滚动方向。action=scroll 时必填。",
        },
        "scroll_steps": {
            "type": "integer",
            "description": "滚轮滚动步数，默认 3。action=scroll 时有效。",
            "default": 3,
            "minimum": 1,
            "maximum": 100,
        },
        "duration": {
            "type": "number",
            "description": "鼠标移动动画时长（秒），默认 0.1。move/drag 时有效。",
            "default": 0.1,
            "minimum": 0,
            "maximum": 5.0,
        },
    },
    "required": ["action"],
}


async def handle_mouse_control(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    执行鼠标控制操作。

    参数:
        parameters: 包含 action（必填）及各类操作对应参数的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本。
    """
    logger.info(f"鼠标控制请求 trace_id={trace_id} parameters={parameters}")

    action: str = parameters.get("action", "")
    x: int = parameters.get("x", 0)
    y: int = parameters.get("y", 0)
    button: str = parameters.get("button", "left")
    end_x: int = parameters.get("end_x", 0)
    end_y: int = parameters.get("end_y", 0)
    scroll_direction: str = parameters.get("scroll_direction", "up")
    scroll_steps: int = parameters.get("scroll_steps", DEFAULT_SCROLL_STEPS)
    duration: float = parameters.get("duration", DEFAULT_MOUSE_MOVE_DURATION)

    # 校验 action
    valid_actions = ("move", "click", "double_click", "drag", "scroll")
    if action not in valid_actions:
        return build_error_result(
            "参数错误",
            f"不支持的鼠标操作: {action}，有效值为 {valid_actions}",
        )

    # 校验按键
    if button not in ("left", "right", "middle"):
        return build_error_result(
            "参数错误",
            f"不支持的鼠标按键: {button}，有效值为 left/right/middle",
        )

    # 校验滚动方向
    if scroll_direction not in ("up", "down"):
        return build_error_result(
            "参数错误",
            f"不支持的滚动方向: {scroll_direction}，有效值为 up/down",
        )

    # 校验坐标
    if action in ("move", "click", "double_click"):
        valid, msg = validate_coordinates(x, y)
        if not valid:
            logger.warning(f"鼠标控制失败 trace_id={trace_id} 原因: 坐标越界 {msg}")
            return build_error_result("坐标越界", msg)
    elif action == "drag":
        valid, msg = validate_coordinates(x, y)
        if not valid:
            logger.warning(f"鼠标控制失败 trace_id={trace_id} 原因: 拖拽起点越界 {msg}")
            return build_error_result("坐标越界", f"拖拽起点: {msg}")
        valid, msg = validate_coordinates(end_x, end_y)
        if not valid:
            logger.warning(f"鼠标控制失败 trace_id={trace_id} 原因: 拖拽终点越界 {msg}")
            return build_error_result("坐标越界", f"拖拽终点: {msg}")

    # 执行操作
    try:
        import pyautogui
        # 禁用 pyautogui 的故障安全特性（移动到角落时抛出异常），由我们自己控制
        pyautogui.FAILSAFE = False
    except ImportError:
        logger.warning(f"鼠标控制失败 trace_id={trace_id} 原因: pyautogui 库未安装")
        return build_error_result("依赖缺失", "pyautogui 库未安装，请执行 pip install pyautogui")

    try:
        if action == "move":
            pyautogui.moveTo(x, y, duration=duration)
            result_msg = f"鼠标已移动到 ({x}, {y})"
            result_extra = {"目标坐标": f"({x}, {y})", "移动时长": f"{duration}s"}

        elif action == "click":
            pyautogui.click(x, y, button=button)
            result_msg = f"鼠标{button}键单击 ({x}, {y})"
            result_extra = {"坐标": f"({x}, {y})", "按键": button}

        elif action == "double_click":
            pyautogui.doubleClick(x, y, button=button)
            result_msg = f"鼠标{button}键双击 ({x}, {y})"
            result_extra = {"坐标": f"({x}, {y})", "按键": button}

        elif action == "drag":
            # 先移动到起点
            pyautogui.moveTo(x, y, duration=duration)
            # 按下拖拽到终点
            pyautogui.dragTo(end_x, end_y, duration=duration, button=button)
            result_msg = f"鼠标{button}键拖拽 ({x}, {y}) → ({end_x}, {end_y})"
            result_extra = {
                "起点": f"({x}, {y})",
                "终点": f"({end_x}, {end_y})",
                "按键": button,
            }

        elif action == "scroll":
            # pyautogui.scroll 正值向上，负值向下
            scroll_amount = scroll_steps if scroll_direction == "up" else -scroll_steps
            pyautogui.scroll(scroll_amount, x=x, y=y)
            result_msg = f"滚轮向{'上' if scroll_direction == 'up' else '下'}滚动 {scroll_steps} 步"
            result_extra = {
                "方向": "向上" if scroll_direction == "up" else "向下",
                "步数": scroll_steps,
            }

        else:
            return build_error_result("参数错误", f"未实现的鼠标操作: {action}")

    except Exception as exc:
        logger.warning(f"鼠标控制失败 trace_id={trace_id} action={action} 原因: {exc!s}")
        return build_error_result("系统错误", f"鼠标操作执行失败: {exc!s}")

    # 获取当前屏幕信息用于结果展示
    try:
        screen_info = get_screen_info()
        result_extra["屏幕DPI"] = f"{screen_info.get('dpi_scale', 1.0):.2f}x"
    except RuntimeError:
        pass

    logger.info(f"鼠标控制成功 trace_id={trace_id} action={action}")
    return build_success_result(result_msg, result_extra)
