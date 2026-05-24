from enum import IntEnum
from typing import Any

from pydantic import BaseModel


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

class ResponseModel(BaseModel):
    """标准 JSON 响应结构"""
    code: int
    msg: str
    data: Any = None
    trace_id: str

def create_success_response(data: Any, trace_id: str) -> ResponseModel:
    return ResponseModel(
        code=ErrorCode.SUCCESS.value,
        msg="success",
        data=data,
        trace_id=trace_id
    )

def create_error_response(code: ErrorCode, msg: str, trace_id: str) -> ResponseModel:
    return ResponseModel(
        code=code.value,
        msg=msg,
        data=None,
        trace_id=trace_id
    )
