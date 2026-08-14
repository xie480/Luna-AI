"""
Desktop Operation Skill 包初始化文件。

做什么：提供桌面自动化能力，包含屏幕截图、应用启动/关闭、鼠标控制、键盘控制等工具。
         覆盖 L0 ~ L3 风险等级，用于验证 Phase 12/13 工具链路与权限治理机制。
"""

from app.skills.desktop_operation.base import ALL_TOOL_NAMES
from app.skills.desktop_operation.tools import (
    TOOL_HANDLERS,
    TOOL_PARAMETER_SCHEMAS,
    handle_close_application,
    handle_keyboard_control,
    handle_mouse_control,
    handle_open_application,
    handle_screenshot,
)

__all__ = [
    "ALL_TOOL_NAMES",
    "TOOL_PARAMETER_SCHEMAS",
    "TOOL_HANDLERS",
    "handle_screenshot",
    "handle_open_application",
    "handle_mouse_control",
    "handle_keyboard_control",
    "handle_close_application",
]
