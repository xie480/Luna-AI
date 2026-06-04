import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

# 创建一个上下文变量，用于存储 trace_id
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="UNKNOWN")

# 敏感信息脱敏正则
SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{32,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9\-\._~+/]+"), "Bearer [REDACTED_TOKEN]"),
]

def sanitize_message(msg: str) -> str:
    """对日志消息进行脱敏"""
    if not isinstance(msg, str):
        return msg
    for pattern, replacement in SENSITIVE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg

def format_record(record: dict[str, Any]) -> str:
    """自定义 JSON 格式化器"""
    # 提取上下文中的 trace_id
    trace_id = record["extra"].get("trace_id", trace_id_var.get())
    parent_span_id = record["extra"].get("parent_span_id", "")

    log_record = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "module": record["name"],
        "message": sanitize_message(record["message"]),
    }

    if record["exception"]:
        log_record["exc_info"] = str(record["exception"])

    # 将 extra 中的其他字段也加入日志
    for key, value in record["extra"].items():
        if key not in ["trace_id", "parent_span_id"]:
            log_record[key] = sanitize_message(str(value))

    record["extra"]["json_str"] = json.dumps(log_record, ensure_ascii=False)
    return "{extra[json_str]}\n"

class InterceptHandler(logging.Handler):
    """拦截标准 logging 并路由到 loguru"""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_logger(level: str = "INFO") -> Any:
    """
    初始化全局日志
    做什么：配置并返回 loguru logger 实例。
    为什么这样做：统一 Python 服务的日志格式，确保所有日志都以 JSON 格式输出，并包含 trace_id，同时进行脱敏。
    输入输出：输入日志级别字符串（如 "INFO"），输出配置好的 logger 对象。
    边界条件：移除默认的 handler，添加自定义的 JSON handler。
    """
    # 移除默认的 handler
    logger.remove()

    # 添加自定义的 JSON handler
    logger.add(
        sys.stdout,
        format=format_record,
        level=level.upper(),
        enqueue=True, # 异步写入
    )
    
    logger.add(
        "luna_ai_debug.log",
        format=format_record,
        level=level.upper(),
        enqueue=True,
    )

    # 拦截标准 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    return logger

# 导出 logger 供其他模块使用
# 其他模块可以直接 from app.logger import logger
