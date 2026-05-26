from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel


class Role(str, Enum):
    """全局统一的角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ErrorCode(IntEnum):
    """全局统一的错误码枚举"""
    SUCCESS = 0
    
    # 系统级错误 (1000-1999)
    SYSTEM_ERROR = 1000
    CONFIG_LOAD_FAILED = 1001
    DB_CONNECT_FAILED = 1002
    
    # 业务逻辑错误 (2000-2999)
    BUSINESS_ERROR = 2000
    STATE_INVALID = 2001
    PERMISSION_DENIED = 2002
    
    # 外部依赖错误 (3000-3999)
    EXTERNAL_ERROR = 3000
    LLM_CALL_FAILED = 3001
    TOOL_EXECUTE_FAILED = 3002


# WebSocket 消息类型常量
WS_MSG_TYPE_PING = "PING"
WS_MSG_TYPE_PONG = "PONG"
WS_MSG_TYPE_CHAT_REQUEST = "CHAT_REQUEST"
WS_MSG_TYPE_CHAT_STREAM = "CHAT_STREAM"
WS_MSG_TYPE_ERROR = "ERROR"


# 健康检查状态常量
HEALTH_STATUS_HEALTHY = "healthy"
HEALTH_STATUS_UNHEALTHY = "unhealthy"
HEALTH_STATUS_DEGRADED = "degraded"


class ResponseModel(BaseModel):
    """标准 JSON 响应结构"""
    code: int
    msg: str
    data: Any = None
    trace_id: str


def create_success_response(data: Any, trace_id: str) -> ResponseModel:
    """创建成功响应"""
    return ResponseModel(
        code=ErrorCode.SUCCESS.value,
        msg="success",
        data=data,
        trace_id=trace_id
    )


def create_error_response(code: ErrorCode, msg: str, trace_id: str) -> ResponseModel:
    """创建错误响应"""
    return ResponseModel(
        code=code.value,
        msg=msg,
        data=None,
        trace_id=trace_id
    )