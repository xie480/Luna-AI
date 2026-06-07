"""
Luna 用户画像 FastAPI 路由。

做什么：提供用户画像查询、手动新增、编辑、删除、缓存状态、缓存重建和手动提取任务 API。
为什么这样做：前端只能通过 Python API 网关操作画像，不能直接访问数据库、Redis 或模型服务。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.logger import logger
from app.types.constants import USER_PROFILE_DEFAULT_USER_ID, UserProfileCategory
from app.types.errors import ErrorCode, ResponseModel, create_error_response, create_success_response
from app.user_profile.schemas import UserProfileExtractionTaskRequest, UserProfileMutationRequest
from app.user_profile.service import UserProfileService
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/user-profile", tags=["user_profile"])


async def get_trace_id(x_trace_id: str | None = Header(None)) -> str:
    """从请求头获取 TraceID，缺失时使用雪花算法生成。"""
    return x_trace_id or generate_string_id()


async def get_user_profile_service(request: Request) -> UserProfileService:
    """从 app.state 获取用户画像服务。"""
    service = getattr(request.app.state, "user_profile_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="用户画像服务未初始化")
    return service


def get_current_user_id() -> str:
    """获取当前本地用户 ID。"""
    return USER_PROFILE_DEFAULT_USER_ID


@router.get("/items", response_model=ResponseModel)
async def list_user_profile_items(
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
    category: UserProfileCategory | None = None,
    include_inactive: bool = False,
) -> ResponseModel:
    """获取全部用户画像，可按类别过滤。"""
    try:
        result = await service.list_items(
            user_id=get_current_user_id(),
            category=category.value if category else None,
            include_inactive=include_inactive,
        )
        return create_success_response(result.model_dump(mode="json"), trace_id)
    except ValueError as exc:
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)
    except Exception as exc:
        logger.error(f"获取用户画像列表失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)


@router.get("/categories/{category}/items", response_model=ResponseModel)
async def list_user_profile_items_by_category(
    category: UserProfileCategory,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """按类别获取用户画像。"""
    try:
        result = await service.list_by_category(user_id=get_current_user_id(), category=category)
        return create_success_response(result.model_dump(mode="json"), trace_id)
    except Exception as exc:
        logger.error(f"按类别获取用户画像失败 trace_id={trace_id} category={category.value} error={exc}")
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)


@router.post("/items", response_model=ResponseModel)
async def create_user_profile_item(
    payload: UserProfileMutationRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ResponseModel:
    """新增手动用户画像。"""
    try:
        result = await service.create_manual(
            user_id=get_current_user_id(),
            request=payload,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        return create_success_response(result.model_dump(mode="json"), trace_id)
    except ValueError as exc:
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)
    except Exception as exc:
        logger.error(f"新增用户画像失败 trace_id={trace_id} error={exc}")
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)


@router.put("/items/{item_id}", response_model=ResponseModel)
async def update_user_profile_item(
    item_id: str,
    payload: UserProfileMutationRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """编辑手动用户画像。"""
    try:
        result = await service.update_manual(
            user_id=get_current_user_id(),
            item_id=item_id,
            request=payload,
            trace_id=trace_id,
        )
        if result is None:
            return create_error_response(ErrorCode.USER_PROFILE_NOT_FOUND, "用户画像不存在", trace_id)
        return create_success_response(result.model_dump(mode="json"), trace_id)
    except ValueError as exc:
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)
    except Exception as exc:
        logger.error(f"编辑用户画像失败 trace_id={trace_id} item_id={item_id} error={exc}")
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)


@router.delete("/items/{item_id}", response_model=ResponseModel)
async def delete_user_profile_item(
    item_id: str,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """软删除用户画像。"""
    try:
        result = await service.delete_manual(user_id=get_current_user_id(), item_id=item_id, trace_id=trace_id)
        if result is None:
            return create_error_response(ErrorCode.USER_PROFILE_NOT_FOUND, "用户画像不存在", trace_id)
        return create_success_response(result, trace_id)
    except Exception as exc:
        logger.error(f"删除用户画像失败 trace_id={trace_id} item_id={item_id} error={exc}")
        return create_error_response(ErrorCode.USER_PROFILE_INVALID_PARAM, str(exc), trace_id)


@router.get("/cache/status", response_model=ResponseModel)
async def get_user_profile_cache_status(
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """查询用户画像压缩缓存状态。"""
    result = await service.get_cache_status(get_current_user_id())
    return create_success_response(result.model_dump(mode="json"), trace_id)


@router.post("/cache/rebuild", response_model=ResponseModel)
async def rebuild_user_profile_cache(
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """触发用户画像压缩缓存重建。"""
    result = service.start_rebuild_summary(user_id=get_current_user_id(), trace_id=trace_id)
    return create_success_response(result.model_dump(mode="json"), trace_id)


@router.post("/extraction/tasks", response_model=ResponseModel)
async def create_user_profile_extraction_task(
    payload: UserProfileExtractionTaskRequest,
    trace_id: Annotated[str, Depends(get_trace_id)],
    service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> ResponseModel:
    """手动触发用户画像提取任务。"""
    result = service.start_extract_from_messages(
        user_id=get_current_user_id(),
        session_id=payload.session_id,
        messages_text=payload.messages_text,
        trace_id=trace_id,
    )
    return create_success_response(result.model_dump(mode="json"), trace_id)
