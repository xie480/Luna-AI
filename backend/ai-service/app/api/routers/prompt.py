"""
Luna AI Prompt 路由

做什么：处理 Prompt 相关的 HTTP 请求。
为什么这样做：提供前端管理提示词模板和版本的接口。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.logger import logger
from app.prompt.manager import Manager as PromptManager
from app.types.errors import ResponseModel, create_error_response, create_success_response
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


class CreateTemplateRequest(BaseModel):
    name: str
    category: str
    slot_position: str
    is_system: bool


class CreateVersionRequest(BaseModel):
    template_id: str
    content: str
    variables: str


class PublishVersionRequest(BaseModel):
    template_id: str
    version_id: str


class RollbackVersionRequest(BaseModel):
    template_id: str
    version_id: str


def get_prompt_manager(request: Request) -> PromptManager:
    return request.app.state.prompt_manager


@router.get("/templates", response_model=ResponseModel)
async def get_templates(request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """获取所有模板列表"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        templates = await mgr.list_templates()
        # 转换为字典列表以符合 JSON 响应
        data = [
            {
                "id": t.id,
                "name": t.name,
                "category": t.category,
                "slot_position": t.slot_position,
                "is_system": t.is_system,
                "active_version_id": t.active_version_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in templates
        ]
        return create_success_response(data, trace_id)
    except Exception as e:
        logger.error(f"获取模板列表失败 error={e}")
        return create_error_response(500, "获取模板列表失败", trace_id)


@router.get("/templates/{id}/versions", response_model=ResponseModel)
async def get_versions(id: str, request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """获取指定模板所有版本历史"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        versions = await mgr.get_versions(id)
        data = [
            {
                "id": v.id,
                "template_id": v.template_id,
                "version_num": v.version_num,
                "content": v.content,
                "variables": v.variables,
                "status": v.status,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]
        return create_success_response(data, trace_id)
    except Exception as e:
        logger.error(f"获取版本历史失败 error={e}")
        return create_error_response(500, "获取版本历史失败", trace_id)


@router.post("/template", response_model=ResponseModel)
async def create_template(req: CreateTemplateRequest, request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """创建模板"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        tmpl = await mgr.create_template(req.name, req.category, req.slot_position, req.is_system)
        data = {
            "id": tmpl.id,
            "name": tmpl.name,
            "category": tmpl.category,
            "slot_position": tmpl.slot_position,
            "is_system": tmpl.is_system,
        }
        return create_success_response(data, trace_id)
    except Exception as e:
        logger.error(f"创建模板失败 error={e}")
        return create_error_response(500, "创建模板失败", trace_id)


@router.post("/version", response_model=ResponseModel)
async def create_version(req: CreateVersionRequest, request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """创建版本"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        version = await mgr.create_version(req.template_id, req.content, req.variables)
        data = {
            "id": version.id,
            "template_id": version.template_id,
            "version_num": version.version_num,
            "content": version.content,
            "variables": version.variables,
            "status": version.status,
        }
        return create_success_response(data, trace_id)
    except Exception as e:
        logger.error(f"创建版本失败 error={e}")
        return create_error_response(500, "创建版本失败", trace_id)


@router.post("/publish", response_model=ResponseModel)
async def publish_version(req: PublishVersionRequest, request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """发布版本"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        await mgr.publish_version(req.template_id, req.version_id)
        return create_success_response({"success": True}, trace_id)
    except Exception as e:
        logger.error(f"发布版本失败 error={e}")
        return create_error_response(500, "发布版本失败", trace_id)


@router.post("/rollback", response_model=ResponseModel)
async def rollback_version(req: RollbackVersionRequest, request: Request, mgr: PromptManager = Depends(get_prompt_manager)) -> ResponseModel:
    """回滚版本"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        await mgr.rollback_version(req.template_id, req.version_id)
        return create_success_response({"success": True}, trace_id)
    except Exception as e:
        logger.error(f"回滚版本失败 error={e}")
        return create_error_response(500, "回滚版本失败", trace_id)


@router.delete("/templates/{template_id}/versions/{version_id}", response_model=ResponseModel)
async def delete_unused_version(
    template_id: str,
    version_id: str,
    request: Request,
    mgr: PromptManager = Depends(get_prompt_manager),
) -> ResponseModel:
    """
    删除未在使用中的 Prompt 旧版本。

    做什么：提供前端历史版本删除入口，只允许删除不属于当前 active_version_id 的旧版本。
    为什么这样做：当前生效版本必须被 Python 控制面保护，避免用户误删导致 Prompt 缓存和模板装配失效。
    输入输出：路径参数包含模板 ID 与版本 ID；成功返回 success=true。
    边界条件：缺少 ID、版本正在使用或版本归属不匹配时返回明确错误。
    异常行为：业务校验失败返回 400；数据库异常返回 500 并记录中文日志。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())

    if not template_id or not version_id:
        return create_error_response(400, "缺少模板 ID 或版本 ID", trace_id)

    try:
        await mgr.delete_unused_version(template_id, version_id)
        return create_success_response({"success": True}, trace_id)
    except ValueError as e:
        logger.warning(f"删除 Prompt 旧版本被拒绝 template_id={template_id} version_id={version_id} error={e}")
        return create_error_response(400, str(e), trace_id)
    except Exception as e:
        logger.error(f"删除 Prompt 旧版本失败 template_id={template_id} version_id={version_id} error={e}")
        return create_error_response(500, "删除 Prompt 旧版本失败", trace_id)
