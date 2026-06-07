"""
Luna AI 错误日志上报 API

做什么：提供前端错误日志上报的 HTTP POST 接口，将异常信息持久化到 PostgreSQL。
为什么这样做：所有前端捕获的异常必须通过此接口持久化到数据库，实现可追溯的错误审计。
接口列表：
    - POST /api/error_logs 接收前端上报的错误日志并持久化

边界条件：
    - 接口使用 Pydantic 模型校验请求体
    - trace_id 从 HTTP Header "X-Trace-ID" 获取，若不存在则自动生成
异常行为：
    - 参数校验失败返回 400
    - 数据库写入失败返回 500，但不会影响前端主流程
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, Query
from pydantic import BaseModel, Field

from app.logger import logger
from app.repository.error_log_pg import ErrorLogPGRepo
from app.repository.models import ErrorLog
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api", tags=["error_log"])


# ============================================================
# 请求 / 响应模型定义
# ============================================================


class ErrorLogReport(BaseModel):
    """前端错误日志上报请求体"""
    level: str = Field(..., description="错误级别：ERROR / WARN / CRITICAL")
    source: str = Field(..., description="错误来源标识，如 react_renderer / websocket / promise")
    message: str = Field(..., description="错误摘要信息")
    detail: str = Field(default="", description="详细错误信息，如 stack trace")
    trace_id: str = Field(default="", description="关联的全链路追踪 ID")


class ErrorLogResponse(BaseModel):
    """错误日志上报响应体"""
    code: int
    msg: str
    id: str = ""


class ErrorLogItem(BaseModel):
    """错误日志列表项"""
    id: str
    level: str
    source: str
    message: str
    detail: str
    trace_id: str
    user_agent: str
    created_at: str  # 日期格式化字符串

class ErrorLogListResponse(BaseModel):
    """错误日志列表响应体"""
    code: int
    msg: str
    data: list[ErrorLogItem]
    total: int


# ============================================================
# 依赖注入
# ============================================================


async def get_error_log_repo(request: Request) -> Optional[ErrorLogPGRepo]:
    """从 app.state 获取 ErrorLogPGRepo 实例"""
    return getattr(request.app.state, "error_log_repo", None)


# ============================================================
# 接口实现
# ============================================================


@router.get("/error_logs", response_model=ErrorLogListResponse)
async def get_error_logs(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    level: Optional[str] = Query(None, description="错误级别"),
    source: Optional[str] = Query(None, description="错误来源"),
    error_log_repo: Optional[ErrorLogPGRepo] = Depends(get_error_log_repo),
) -> ErrorLogListResponse:
    """
    分页查询前端错误日志
    """
    if not error_log_repo:
        return ErrorLogListResponse(code=500, msg="错误日志仓库不可用", data=[], total=0)

    limit = page_size
    offset = (page - 1) * page_size

    total = await error_log_repo.count_error_logs(level=level, source=source)
    logs = await error_log_repo.get_error_logs(limit=limit, offset=offset, level=level, source=source)

    items = []
    for log in logs:
        items.append(ErrorLogItem(
            id=log.id,
            level=log.level,
            source=log.source,
            message=log.message,
            detail=log.detail,
            trace_id=log.trace_id,
            user_agent=log.user_agent,
            created_at=log.created_at.isoformat() if log.created_at else "",
        ))

    return ErrorLogListResponse(code=0, msg="success", data=items, total=total)


@router.post("/error_logs", response_model=ErrorLogResponse)
async def report_error_log(
    report: ErrorLogReport,
    request: Request,
    x_trace_id: Optional[str] = Header(None),
    error_log_repo: Optional[ErrorLogPGRepo] = Depends(get_error_log_repo),
) -> ErrorLogResponse:
    """
    接收前端上报的错误日志并持久化到 PostgreSQL

    做什么：将前端捕获的异常信息写入 error_logs 表。
    为什么这样做：所有异常必须有可追溯的持久化记录，不能仅存于内存。
    输入：ErrorLogReport { level, source, message, detail, trace_id }
    输出：ErrorLogResponse { code, msg, id }
    边界条件：
        - 数据库不可用时返回降级响应，不抛异常影响前端
        - trace_id 优先使用前端传入的，其次从请求头获取
    """
    # 确定 trace_id：优先使用前端上报的，其次从 Header 获取，最后自动生成
    trace_id = report.trace_id or x_trace_id or generate_string_id()

    # 验证 level 字段合法性
    valid_levels = {"ERROR", "WARN", "CRITICAL"}
    if report.level not in valid_levels:
        return ErrorLogResponse(
            code=400,
            msg=f"无效的错误级别: {report.level}，有效值: {', '.join(valid_levels)}",
            id="",
        )

    # 验证必填字段
    if not report.source or not report.message:
        return ErrorLogResponse(
            code=400,
            msg="source 和 message 为必填字段",
            id="",
        )

    # 如果没有仓库实例，返回降级响应
    if not error_log_repo:
        logger.warning(f"错误日志仓库不可用，跳过持久化 trace_id={trace_id}")
        return ErrorLogResponse(
            code=200,
            msg="前端错误已记录（数据库不可用，仅内存留存）",
            id="",
        )

    # 构建 ORM 模型
    error_id = generate_string_id()
    error_log = ErrorLog(
        id=error_id,
        level=report.level,
        source=report.source,
        message=report.message,
        detail=report.detail,
        trace_id=trace_id,
        user_agent=request.headers.get("user-agent", ""),
    )

    try:
        # 持久化到 PostgreSQL
        await error_log_repo.save_error_log(error_log)
        logger.info(f"前端错误日志已持久化 id={error_id} trace_id={trace_id} level={report.level} source={report.source}")

        return ErrorLogResponse(
            code=0,
            msg="前端错误已记录并持久化",
            id=error_id,
        )
    except Exception as e:
        logger.error(f"持久化前端错误日志失败 trace_id={trace_id} error={e}")
        return ErrorLogResponse(
            code=500,
            msg=f"错误日志持久化失败: {str(e)}",
            id="",
        )
