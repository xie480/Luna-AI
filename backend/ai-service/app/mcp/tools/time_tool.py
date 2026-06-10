"""
MCP 内置工具：获取当前系统时间。

做什么：提供获取当前系统时间的工具实现，支持指定输出格式和时区。
        作为 L0 级低危工具，直接放行无需用户确认。
为什么这样做：Phase 12 需要接入至少一个 L0 级低危工具来验证完整的
             工具注册→初筛→执行→对齐链路。时间工具是最简单的工具，
             不依赖外部 API，不涉及敏感数据。
边界条件：
    - 支持 format 参数指定日期时间格式（默认：%Y-%m-%d %H:%M:%S）。
    - 支持 timezone 参数指定时区（默认：Asia/Shanghai）。
    - 时区无效时回退到 UTC。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytz

from app.logger import logger


# ============================================================
# 时间工具的 parameters_schema（JSON Schema 格式）
# ============================================================

TIME_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {
            "type": "string",
            "description": "日期时间格式，使用 strftime 格式语法。默认：%Y-%m-%d %H:%M:%S",
            "default": "%Y-%m-%d %H:%M:%S",
        },
        "timezone": {
            "type": "string",
            "description": "时区名称，使用 IANA 时区数据库格式。默认：Asia/Shanghai",
            "default": "Asia/Shanghai",
        },
    },
    "required": [],
}


# ============================================================
# 工具执行 Handler
# ============================================================


async def handle_get_current_time(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    获取当前系统时间的工具 handler。

    做什么：根据传入的参数（format 和 timezone），获取当前系统时间
            并按照指定格式和时区格式化为字符串返回。
    为什么这样做：TimeTool 是 MCP 工具链路的 L0 级低危入门工具，
                 用于验证工具注册→初筛→执行→对齐的完整流程。
    参数:
        parameters: 包含 format 和 timezone 字段的字典。
                    - format（可选）：strftime 格式字符串。
                    - timezone（可选）：IANA 时区名称。
        trace_id: 全链路追踪 ID。
    返回:
        str: 格式化后的当前时间字符串。
    边界条件:
        - 未指定 format 时使用默认格式 "%Y-%m-%d %H:%M:%S"。
        - 未指定 timezone 时使用 "Asia/Shanghai"。
        - timezone 无效时回退到 UTC。
    """
    fmt = parameters.get("format", "%Y-%m-%d %H:%M:%S")
    tz_name = parameters.get("timezone", "Asia/Shanghai")

    # 解析时区，无效时回退到 UTC
    try:
        tz = pytz.timezone(tz_name)
    except (pytz.UnknownTimeZoneError, Exception):
        logger.warning(
            f"MCP 时间工具时区无效 trace_id={trace_id} "
            f"timezone={tz_name}，回退到 UTC"
        )
        tz = timezone.utc

    # 获取当前时间并格式化
    now = datetime.now(tz)
    formatted_time = now.strftime(fmt)

    logger.info(
        f"MCP 时间工具执行成功 trace_id={trace_id} "
        f"timezone={tz_name} format={fmt} "
        f"result={formatted_time}"
    )

    return formatted_time
