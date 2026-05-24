import logging
import sys
from contextvars import ContextVar
from typing import Any

# 创建一个上下文变量，用于存储 trace_id
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

class JSONFormatter(logging.Formatter):
    """自定义 JSON 格式化器"""
    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "trace_id": trace_id_var.get(),
            "module": record.module,
            "message": record.getMessage(),
        }
        
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
            
        import json
        return json.dumps(log_record)

def setup_logger(level: str = "INFO") -> logging.Logger:
    """
    初始化全局日志
    做什么：配置并返回一个带有 JSONFormatter 的全局 logging.Logger 实例。
    为什么这样做：统一 Python 服务的日志格式，确保所有日志都以 JSON 格式输出，并包含 trace_id。
    输入输出：输入日志级别字符串（如 "INFO"），输出配置好的 logging.Logger 对象。
    边界条件：如果 logger 已经配置过 handler，则不会重复添加。
    异常行为：如果传入的 level 字符串不合法，logging.setLevel 可能会抛出 ValueError。
    """
    logger = logging.getLogger("luna_ai")
    logger.setLevel(level.upper())
    
    # 避免重复添加 handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = JSONFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

logger = setup_logger()
