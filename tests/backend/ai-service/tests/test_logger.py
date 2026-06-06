import json
import sys
from io import StringIO

from loguru import logger
from app.logger import trace_id_var, format_record, setup_logger


def test_logger_format_and_trace_id() -> None:
    """
    测试日志格式和 TraceID 注入
    做什么：验证日志输出是否为 JSON 格式，且包含正确的 trace_id 字段。
    为什么这样做：确保全链路追踪的 TraceID 能够正确落盘，满足可观测性要求。
    输入输出：设置 trace_id_var 上下文变量，输出捕获的日志字符串。
    边界条件：trace_id_var 未设置时，应输出空字符串。
    异常行为：如果 JSON 解析失败，测试将报错。
    """
    # 1. 设置 logger 和 buffer
    logger.remove()
    buf = StringIO()
    logger.add(buf, format=format_record, level="INFO")
    
    # 2. 设置 trace_id
    token = trace_id_var.set("test-trace-123")
    
    try:
        # 3. 记录日志
        logger.info("test message")
        
        # 4. 解析输出的 JSON
        log_output = json.loads(buf.getvalue())
        
        # 5. 验证字段
        assert log_output["message"] == "test message"
        assert log_output["trace_id"] == "test-trace-123"
        assert log_output["level"] == "INFO"
        assert "timestamp" in log_output
    finally:
        # 恢复上下文
        trace_id_var.reset(token)
