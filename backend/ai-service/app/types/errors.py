from enum import IntEnum
from typing import Any, Union
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
    
    # 用户画像错误 (2400-2499)
    USER_PROFILE_INVALID_PARAM = 2400
    USER_PROFILE_NOT_FOUND = 2401
    USER_PROFILE_DUPLICATE = 2402
    USER_PROFILE_CACHE_REBUILDING = 2403
    USER_PROFILE_EXTRACTION_FAILED = 2404
    USER_PROFILE_CONFLICT_FAILED = 2405
    
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
    """创建成功响应"""
    return ResponseModel(
        code=ErrorCode.SUCCESS.value,
        msg="success",
        data=data,
        trace_id=trace_id
    )

def create_error_response(code: Union[ErrorCode, int], msg: str, trace_id: str) -> ResponseModel:
    """
    创建错误响应

    做什么：生成统一的错误响应对象。
            支持传入 ErrorCode 枚举或直接传入 int 类型 HTTP 状态码。
    为什么这样做：部分调用方直接使用 int (如 400/500) 传参，
                 而 create_error_response 内部尝试调用 int.value 导致 AttributeError。
    """
    code_val = code.value if isinstance(code, ErrorCode) else code
    return ResponseModel(
        code=code_val,
        msg=msg,
        data=None,
        trace_id=trace_id
    )
