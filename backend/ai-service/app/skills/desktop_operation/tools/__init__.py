"""
Desktop Operation 工具模块导出。

做什么：统一导出所有 5 个工具的参数 Schema 和 Handler。
"""

from app.skills.desktop_operation.base import (
    ALL_TOOL_NAMES,
    TOOL_NAME_CLOSE_APPLICATION,
    TOOL_NAME_KEYBOARD_CONTROL,
    TOOL_NAME_MOUSE_CONTROL,
    TOOL_NAME_OPEN_APPLICATION,
    TOOL_NAME_SCREENSHOT,
)

from .screenshot import (
    PARAMETER_SCHEMA as SCREENSHOT_SCHEMA,
    handle_screenshot,
)
from .open_application import (
    PARAMETER_SCHEMA as OPEN_APPLICATION_SCHEMA,
    handle_open_application,
)
from .mouse_control import (
    PARAMETER_SCHEMA as MOUSE_CONTROL_SCHEMA,
    handle_mouse_control,
)
from .keyboard_control import (
    PARAMETER_SCHEMA as KEYBOARD_CONTROL_SCHEMA,
    handle_keyboard_control,
)
from .close_application import (
    PARAMETER_SCHEMA as CLOSE_APPLICATION_SCHEMA,
    handle_close_application,
)


# 工具参数 Schema 映射（按工具名索引）
TOOL_PARAMETER_SCHEMAS: dict[str, object] = {
    TOOL_NAME_SCREENSHOT: SCREENSHOT_SCHEMA,
    TOOL_NAME_OPEN_APPLICATION: OPEN_APPLICATION_SCHEMA,
    TOOL_NAME_MOUSE_CONTROL: MOUSE_CONTROL_SCHEMA,
    TOOL_NAME_KEYBOARD_CONTROL: KEYBOARD_CONTROL_SCHEMA,
    TOOL_NAME_CLOSE_APPLICATION: CLOSE_APPLICATION_SCHEMA,
}

# 工具 Handler 映射（按工具名索引）
TOOL_HANDLERS: dict[str, object] = {
    TOOL_NAME_SCREENSHOT: handle_screenshot,
    TOOL_NAME_OPEN_APPLICATION: handle_open_application,
    TOOL_NAME_MOUSE_CONTROL: handle_mouse_control,
    TOOL_NAME_KEYBOARD_CONTROL: handle_keyboard_control,
    TOOL_NAME_CLOSE_APPLICATION: handle_close_application,
}


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
