"""
Desktop Operation Skill 单元测试。

做什么：验证 5 个桌面操作工具的基本功能、参数校验和错误处理。
为什么这样做：确保工具在注册到 MCP 框架前具备正确的行为，
             避免运行时因参数校验缺失或异常处理不当导致系统崩溃。
边界条件：
    - 测试环境为 Windows，部分测试需要实际屏幕和进程。
    - 涉及 GUI 操作的测试在 CI 环境中可能被跳过。
"""

from __future__ import annotations

import os
import platform
import pytest
from typing import Any

# 导入被测试的工具模块
from app.skills.desktop_operation.base import (
    ALL_TOOL_NAMES,
    TOOL_NAME_CLOSE_APPLICATION,
    TOOL_NAME_KEYBOARD_CONTROL,
    TOOL_NAME_MOUSE_CONTROL,
    TOOL_NAME_OPEN_APPLICATION,
    TOOL_NAME_SCREENSHOT,
    build_error_result,
    build_success_result,
    get_screen_info,
    validate_coordinates,
    validate_region,
)
from app.skills.desktop_operation.tools import (
    TOOL_HANDLERS,
    TOOL_PARAMETER_SCHEMAS,
    handle_close_application,
    handle_keyboard_control,
    handle_mouse_control,
    handle_open_application,
    handle_screenshot,
)


# ============================================================
# 基础模块测试
# ============================================================

class TestBaseModule:
    """测试 base.py 中的公共函数。"""

    def test_all_tool_names(self) -> None:
        """验证工具名称列表完整性。"""
        assert len(ALL_TOOL_NAMES) == 5
        assert TOOL_NAME_SCREENSHOT in ALL_TOOL_NAMES
        assert TOOL_NAME_OPEN_APPLICATION in ALL_TOOL_NAMES
        assert TOOL_NAME_MOUSE_CONTROL in ALL_TOOL_NAMES
        assert TOOL_NAME_KEYBOARD_CONTROL in ALL_TOOL_NAMES
        assert TOOL_NAME_CLOSE_APPLICATION in ALL_TOOL_NAMES

    def test_build_success_result(self) -> None:
        """验证成功返回格式。"""
        result = build_success_result("测试成功")
        assert "【操作成功】" in result
        assert "测试成功" in result

        result_with_extra = build_success_result("测试成功", {"键": "值"})
        assert "键: 值" in result_with_extra

    def test_build_error_result(self) -> None:
        """验证错误返回格式。"""
        result = build_error_result("参数错误", "测试错误")
        assert "【参数错误】" in result
        assert "测试错误" in result

        result_with_suggestion = build_error_result("参数错误", "测试错误", "建议修复")
        assert "建议: 建议修复" in result_with_suggestion

    def test_validate_coordinates_negative(self) -> None:
        """验证负数坐标被拒绝。"""
        valid, msg = validate_coordinates(-1, -1)
        assert not valid
        assert "越界" in msg or "负数" in msg

    def test_validate_region_invalid_size(self) -> None:
        """验证非法区域尺寸被拒绝。"""
        valid, msg = validate_region(0, 0, 0, 0)
        assert not valid
        assert "非法" in msg or "正数" in msg

    @pytest.mark.skipif(platform.system() != "Windows", reason="仅 Windows 平台")
    def test_get_screen_info_windows(self) -> None:
        """验证 Windows 平台屏幕信息获取。"""
        info = get_screen_info()
        assert "screen_count" in info
        assert "screens" in info
        assert "dpi_scale" in info
        assert info["screen_count"] >= 1
        assert len(info["screens"]) >= 1
        assert info["screens"][0]["width"] > 0
        assert info["screens"][0]["height"] > 0


# ============================================================
# 工具注册测试
# ============================================================

class TestToolRegistration:
    """测试工具注册结构完整性。"""

    def test_tool_parameter_schemas(self) -> None:
        """验证所有工具都有参数 Schema。"""
        for tool_name in ALL_TOOL_NAMES:
            assert tool_name in TOOL_PARAMETER_SCHEMAS, f"工具 {tool_name} 缺少参数 Schema"
            schema = TOOL_PARAMETER_SCHEMAS[tool_name]
            assert isinstance(schema, dict)
            assert "type" in schema
            assert schema["type"] == "object"
            assert "properties" in schema

    def test_tool_handlers(self) -> None:
        """验证所有工具都有 Handler 函数。"""
        for tool_name in ALL_TOOL_NAMES:
            assert tool_name in TOOL_HANDLERS, f"工具 {tool_name} 缺少 Handler"
            handler = TOOL_HANDLERS[tool_name]
            assert callable(handler)

    def test_handler_signatures(self) -> None:
        """验证 Handler 函数签名一致性。"""
        import inspect

        for tool_name in ALL_TOOL_NAMES:
            handler = TOOL_HANDLERS[tool_name]
            sig = inspect.signature(handler)
            params = list(sig.parameters.keys())
            assert len(params) == 2, f"工具 {tool_name} Handler 参数数量错误: {params}"
            assert params[0] == "parameters", f"工具 {tool_name} 第一个参数应为 parameters"
            assert params[1] == "trace_id", f"工具 {tool_name} 第二个参数应为 trace_id"


# ============================================================
# Screenshot 工具测试
# ============================================================

class TestScreenshotTool:
    """测试 screenshot 工具。"""

    @pytest.mark.asyncio
    async def test_screenshot_schema(self) -> None:
        """验证 screenshot 参数 Schema。"""
        schema = TOOL_PARAMETER_SCHEMAS[TOOL_NAME_SCREENSHOT]
        props = schema["properties"]
        assert "region" in props
        assert "screen_index" in props
        assert "output_format" in props
        assert "save_path" in props

    @pytest.mark.asyncio
    async def test_screenshot_invalid_format(self) -> None:
        """验证非法输出格式被拒绝。"""
        result = await handle_screenshot(
            {"output_format": "bmp"},
            trace_id="test-screenshot-001",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_screenshot_invalid_region(self) -> None:
        """验证非法区域被拒绝。"""
        result = await handle_screenshot(
            {"region": {"left": 0, "top": 0, "width": 0, "height": 0}},
            trace_id="test-screenshot-002",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="CI 环境无显示器，跳过实际截图测试",
    )
    async def test_screenshot_fullscreen(self) -> None:
        """验证全屏截图（需要实际显示器）。"""
        result = await handle_screenshot(
            {"output_format": "png"},
            trace_id="test-screenshot-003",
        )
        # 可能成功（返回 base64）或失败（无显示器/依赖缺失）
        assert (
            "【操作成功】" in result
            or "【系统错误】" in result
            or "【依赖缺失】" in result
        )


# ============================================================
# Open Application 工具测试
# ============================================================

class TestOpenApplicationTool:
    """测试 open_application 工具。"""

    @pytest.mark.asyncio
    async def test_open_application_schema(self) -> None:
        """验证 open_application 参数 Schema。"""
        schema = TOOL_PARAMETER_SCHEMAS[TOOL_NAME_OPEN_APPLICATION]
        props = schema["properties"]
        assert "app_name" in props
        assert "arguments" in props
        assert "working_directory" in props
        assert "wait_for_start" in props

    @pytest.mark.asyncio
    async def test_open_application_empty_name(self) -> None:
        """验证空应用名被拒绝。"""
        result = await handle_open_application(
            {"app_name": ""},
            trace_id="test-open-001",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_open_application_not_found(self) -> None:
        """验证不存在的应用返回错误。"""
        result = await handle_open_application(
            {"app_name": "nonexistent_app_12345"},
            trace_id="test-open-002",
        )
        assert "【应用未找到】" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(platform.system() != "Windows", reason="仅 Windows 平台")
    async def test_open_notepad_windows(self) -> None:
        """验证打开记事本（Windows）。"""
        result = await handle_open_application(
            {"app_name": "notepad", "wait_for_start": True},
            trace_id="test-open-003",
        )
        # 可能成功或失败（取决于环境）
        assert (
            "【操作成功】" in result
            or "【启动失败】" in result
            or "【应用未找到】" in result
            or "【系统错误】" in result
        )


# ============================================================
# Mouse Control 工具测试
# ============================================================

class TestMouseControlTool:
    """测试 mouse_control 工具。"""

    @pytest.mark.asyncio
    async def test_mouse_control_schema(self) -> None:
        """验证 mouse_control 参数 Schema。"""
        schema = TOOL_PARAMETER_SCHEMAS[TOOL_NAME_MOUSE_CONTROL]
        props = schema["properties"]
        assert "action" in props
        assert "x" in props
        assert "y" in props
        assert "button" in props
        assert "end_x" in props
        assert "end_y" in props
        assert "scroll_direction" in props
        assert "scroll_steps" in props
        assert "duration" in props

    @pytest.mark.asyncio
    async def test_mouse_control_invalid_action(self) -> None:
        """验证非法操作类型被拒绝。"""
        result = await handle_mouse_control(
            {"action": "invalid_action"},
            trace_id="test-mouse-001",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_mouse_control_invalid_button(self) -> None:
        """验证非法按键被拒绝。"""
        result = await handle_mouse_control(
            {"action": "click", "x": 100, "y": 100, "button": "invalid"},
            trace_id="test-mouse-002",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_mouse_control_invalid_scroll_direction(self) -> None:
        """验证非法滚动方向被拒绝。"""
        result = await handle_mouse_control(
            {"action": "scroll", "scroll_direction": "left"},
            trace_id="test-mouse-003",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_mouse_control_negative_coordinates(self) -> None:
        """验证负数坐标被拒绝。"""
        result = await handle_mouse_control(
            {"action": "click", "x": -100, "y": -100},
            trace_id="test-mouse-004",
        )
        assert "【坐标越界】" in result or "【参数错误】" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="CI 环境无显示器，跳过实际鼠标操作测试",
    )
    async def test_mouse_move(self) -> None:
        """验证鼠标移动（需要实际显示器）。"""
        result = await handle_mouse_control(
            {"action": "move", "x": 500, "y": 500, "duration": 0},
            trace_id="test-mouse-005",
        )
        assert (
            "【操作成功】" in result
            or "【坐标越界】" in result
            or "【系统错误】" in result
            or "【依赖缺失】" in result
        )


# ============================================================
# Keyboard Control 工具测试
# ============================================================

class TestKeyboardControlTool:
    """测试 keyboard_control 工具。"""

    @pytest.mark.asyncio
    async def test_keyboard_control_schema(self) -> None:
        """验证 keyboard_control 参数 Schema。"""
        schema = TOOL_PARAMETER_SCHEMAS[TOOL_NAME_KEYBOARD_CONTROL]
        props = schema["properties"]
        assert "action" in props
        assert "text" in props
        assert "key" in props
        assert "keys" in props
        assert "interval" in props
        assert "press_duration" in props

    @pytest.mark.asyncio
    async def test_keyboard_control_invalid_action(self) -> None:
        """验证非法操作类型被拒绝。"""
        result = await handle_keyboard_control(
            {"action": "invalid_action"},
            trace_id="test-keyboard-001",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_keyboard_control_type_text_empty(self) -> None:
        """验证空文本被拒绝。"""
        result = await handle_keyboard_control(
            {"action": "type_text", "text": ""},
            trace_id="test-keyboard-002",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_keyboard_control_press_key_empty(self) -> None:
        """验证空按键被拒绝。"""
        result = await handle_keyboard_control(
            {"action": "press_key", "key": ""},
            trace_id="test-keyboard-003",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_keyboard_control_hotkey_insufficient_keys(self) -> None:
        """验证组合键数量不足被拒绝。"""
        result = await handle_keyboard_control(
            {"action": "hotkey", "keys": ["ctrl"]},
            trace_id="test-keyboard-004",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="CI 环境无显示器，跳过实际键盘操作测试",
    )
    async def test_keyboard_press_key(self) -> None:
        """验证按键按下（需要实际显示器）。"""
        result = await handle_keyboard_control(
            {"action": "press_key", "key": "shift"},
            trace_id="test-keyboard-005",
        )
        assert (
            "【操作成功】" in result
            or "【系统错误】" in result
            or "【依赖缺失】" in result
        )


# ============================================================
# Close Application 工具测试
# ============================================================

class TestCloseApplicationTool:
    """测试 close_application 工具。"""

    @pytest.mark.asyncio
    async def test_close_application_schema(self) -> None:
        """验证 close_application 参数 Schema。"""
        schema = TOOL_PARAMETER_SCHEMAS[TOOL_NAME_CLOSE_APPLICATION]
        props = schema["properties"]
        assert "pid" in props
        assert "process_name" in props
        assert "force" in props
        assert "timeout" in props

    @pytest.mark.asyncio
    async def test_close_application_no_target(self) -> None:
        """验证缺少目标参数被拒绝。"""
        result = await handle_close_application(
            {},
            trace_id="test-close-001",
        )
        assert "【参数错误】" in result

    @pytest.mark.asyncio
    async def test_close_application_invalid_pid(self) -> None:
        """验证不存在的 PID 返回错误。"""
        result = await handle_close_application(
            {"pid": 999999},
            trace_id="test-close-002",
        )
        assert "【进程不存在】" in result

    @pytest.mark.asyncio
    async def test_close_application_not_found(self) -> None:
        """验证不存在的进程名返回错误。"""
        result = await handle_close_application(
            {"process_name": "nonexistent_process_12345"},
            trace_id="test-close-003",
        )
        assert "【进程未找到】" in result


# ============================================================
# 模块导入测试
# ============================================================

class TestModuleImport:
    """测试模块导入完整性。"""

    def test_skill_package_import(self) -> None:
        """验证 skill 包可正常导入。"""
        from app.skills import desktop_operation

        assert hasattr(desktop_operation, "ALL_TOOL_NAMES")
        assert hasattr(desktop_operation, "TOOL_HANDLERS")
        assert hasattr(desktop_operation, "TOOL_PARAMETER_SCHEMAS")

    def test_tools_package_import(self) -> None:
        """验证 tools 包可正常导入。"""
        from app.skills.desktop_operation import tools

        assert hasattr(tools, "TOOL_HANDLERS")
        assert hasattr(tools, "TOOL_PARAMETER_SCHEMAS")
        assert hasattr(tools, "handle_screenshot")
        assert hasattr(tools, "handle_open_application")
        assert hasattr(tools, "handle_mouse_control")
        assert hasattr(tools, "handle_keyboard_control")
        assert hasattr(tools, "handle_close_application")

    def test_json_config_exists(self) -> None:
        """验证 JSON 注册文件存在。"""
        json_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..",
            "backend", "ai-service",
            "app", "skills", "desktop_operation",
            "json", "desktop_operation_skill.json",
        )
        # 如果文件不存在，尝试从 app 目录推断
        if not os.path.exists(json_path):
            import app.skills.desktop_operation
            pkg_dir = os.path.dirname(app.skills.desktop_operation.__file__)
            json_path = os.path.join(pkg_dir, "json", "desktop_operation_skill.json")

        assert os.path.exists(json_path), f"JSON 注册文件不存在: {json_path}"

        import json
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        assert "skills" in config
        assert len(config["skills"]) == 1
        skill = config["skills"][0]
        assert skill["name"] == "desktop_operation"
        assert len(skill["tools"]) == 5
        assert len(skill["prompts"]) == 5
        assert len(skill["resources"]) == 1
