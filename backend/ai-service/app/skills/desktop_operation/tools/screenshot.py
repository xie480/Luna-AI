"""
MCP 工具：屏幕截图。

做什么：捕获当前屏幕画面，支持全屏截图与指定区域截图，支持多显示器选择。
         返回 base64 编码图片或保存为本地文件。
风险等级：L0（低危，只读操作，无副作用，不需要前端 Gating 确认）。
"""

from __future__ import annotations

import os
from typing import Any

from app.logger import logger
from app.skills.desktop_operation.base import (
    DEFAULT_SCREENSHOT_FORMAT,
    build_error_result,
    build_success_result,
    get_screen_info,
    image_to_base64,
    save_image_to_file,
    validate_region,
)

# ============================================================
# 参数 Schema
# ============================================================

PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "region": {
            "type": "object",
            "description": "可选。指定截图区域，不传则截取全屏。",
            "properties": {
                "left": {"type": "integer", "description": "区域左上角 X 坐标"},
                "top": {"type": "integer", "description": "区域左上角 Y 坐标"},
                "width": {"type": "integer", "description": "区域宽度（像素）", "minimum": 1},
                "height": {"type": "integer", "description": "区域高度（像素）", "minimum": 1},
            },
            "required": ["left", "top", "width", "height"],
        },
        "screen_index": {
            "type": "integer",
            "description": "目标显示器索引，0 为主显示器。多屏场景下可指定其他屏幕。默认 0。",
            "default": 0,
            "minimum": 0,
        },
        "output_format": {
            "type": "string",
            "enum": ["png", "jpeg"],
            "description": "输出图片格式，默认 png。",
            "default": "png",
        },
        "save_path": {
            "type": "string",
            "description": "可选。截图保存的绝对文件路径。若不传则返回 base64 编码字符串。",
            "maxLength": 1024,
        },
    },
    "required": [],
}


async def handle_screenshot(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    捕获屏幕截图。

    参数:
        parameters: 包含 region（可选）、screen_index（可选）、
                    output_format（可选）、save_path（可选）的字典。
        trace_id: 全链路追踪 ID。
    返回:
        str: 操作结果文本，成功时包含 base64 数据或文件路径。
    """
    logger.info(f"截图请求 trace_id={trace_id} parameters={parameters}")

    region: dict[str, int] | None = parameters.get("region")
    screen_index: int = parameters.get("screen_index", 0)
    output_format: str = parameters.get("output_format", DEFAULT_SCREENSHOT_FORMAT)
    save_path: str = parameters.get("save_path", "")

    # 校验输出格式
    if output_format not in ("png", "jpeg"):
        return build_error_result("参数错误", f"不支持的输出格式: {output_format}，仅支持 png/jpeg")

    # 校验区域参数
    if region:
        left = region.get("left", 0)
        top = region.get("top", 0)
        width = region.get("width", 0)
        height = region.get("height", 0)

        valid, msg = validate_region(left, top, width, height, screen_index)
        if not valid:
            logger.warning(f"截图失败 trace_id={trace_id} 原因: 区域校验失败 {msg}")
            return build_error_result("参数错误", f"截图区域非法: {msg}")

    # 获取屏幕信息以确定截图范围
    try:
        screen_info = get_screen_info()
    except RuntimeError as exc:
        logger.warning(f"截图失败 trace_id={trace_id} 原因: 获取屏幕信息失败 {exc!s}")
        return build_error_result("系统错误", f"无法获取屏幕信息: {exc!s}")

    screens = screen_info.get("screens", [])
    if screen_index >= len(screens):
        return build_error_result(
            "参数错误",
            f"显示器索引越界: screen_index={screen_index}，当前共有 {len(screens)} 个显示器",
        )

    target_screen = screens[screen_index]

    # 确定截图范围
    if region:
        capture_left = region["left"]
        capture_top = region["top"]
        capture_width = region["width"]
        capture_height = region["height"]
    else:
        capture_left = target_screen["left"]
        capture_top = target_screen["top"]
        capture_width = target_screen["width"]
        capture_height = target_screen["height"]

    # 执行截图
    try:
        import mss
        import mss.tools
    except ImportError:
        logger.warning(f"截图失败 trace_id={trace_id} 原因: mss 库未安装")
        return build_error_result("依赖缺失", "mss 截图库未安装，请执行 pip install mss")

    try:
        with mss.mss() as sct:
            # mss 的 monitor 索引从 1 开始（0 是全部屏幕的合并）
            monitor = sct.monitors[screen_index + 1] if screen_index + 1 < len(sct.monitors) else sct.monitors[1]

            # 构建截图区域
            if region:
                # 区域截图：使用用户指定的坐标（虚拟屏幕坐标系）
                monitor_region = {
                    "left": capture_left,
                    "top": capture_top,
                    "width": capture_width,
                    "height": capture_height,
                }
            else:
                # 全屏截图：使用 mss 的 monitor 定义
                monitor_region = {
                    "left": monitor["left"],
                    "top": monitor["top"],
                    "width": monitor["width"],
                    "height": monitor["height"],
                }

            # 捕获屏幕
            screenshot = sct.grab(monitor_region)

            # 转换为指定格式
            img_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)

            # 如果需要 JPEG 格式，使用 Pillow 转换
            if output_format == "jpeg":
                try:
                    from PIL import Image
                    img = Image.open(__import__("io").BytesIO(img_bytes))
                    buf = __import__("io").BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                except ImportError:
                    logger.warning(f"截图警告 trace_id={trace_id} Pillow 未安装，降级为 PNG 格式")
                    output_format = "png"

    except Exception as exc:
        logger.warning(f"截图失败 trace_id={trace_id} 原因: {exc!s}")
        return build_error_result("系统错误", f"截图捕获失败: {exc!s}")

    # 构建返回结果
    result_extra: dict[str, Any] = {
        "截图范围": f"({capture_left}, {capture_top}) {capture_width}x{capture_height}",
        "显示器": f"#{screen_index} ({'主屏' if target_screen.get('is_primary') else '副屏'})",
        "DPI缩放": f"{screen_info.get('dpi_scale', 1.0):.2f}x",
    }

    if save_path:
        # 保存为文件
        try:
            saved_path = save_image_to_file(img_bytes, save_path)
            file_size = os.path.getsize(saved_path)
            result_extra["文件路径"] = saved_path
            result_extra["文件大小"] = f"{file_size / 1024:.1f} KB"
            logger.info(f"截图成功 trace_id={trace_id} 保存至 {saved_path}")
            return build_success_result("截图已保存到本地文件", result_extra)
        except OSError as exc:
            logger.warning(f"截图保存失败 trace_id={trace_id} 原因: {exc!s}")
            return build_error_result("文件错误", f"截图保存失败: {exc!s}")
    else:
        # 返回 base64
        b64_data = image_to_base64(img_bytes, output_format)
        result_extra["编码格式"] = output_format.upper()
        result_extra["数据长度"] = f"{len(b64_data) / 1024:.1f} KB"
        logger.info(f"截图成功 trace_id={trace_id} base64 长度={len(b64_data)}")

        # base64 数据可能很长，单独作为一行返回
        header = build_success_result("截图完成（base64 编码）", result_extra)
        return f"{header}\n\n[BASE64_IMAGE_DATA_START]\n{b64_data}\n[BASE64_IMAGE_DATA_END]"
