"""
Luna AI API 配置预设路由

做什么：处理 API 配置预设相关的 HTTP 请求。
为什么这样做：提供前端管理大、中、小模型配置的接口。
"""

import json
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.logger import logger
from app.repository.config_preset_pg import ConfigPresetPGRepo
from app.repository.models import ApiConfigPreset
from app.types.errors import ResponseModel, create_error_response, create_success_response
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/api/v1/config/presets", tags=["config_presets"])


class ModelConfig(BaseModel):
    base_url: str
    api_key: str
    model_id: str
    max_tokens: int
    max_context_tokens: int
    temperature: float


class PresetRequest(BaseModel):
    id: str
    name: str
    large_model_config: ModelConfig
    medium_model_config: ModelConfig
    small_model_config: ModelConfig


class PresetResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    large_model_config: ModelConfig
    medium_model_config: ModelConfig
    small_model_config: ModelConfig


class FetchModelsRequest(BaseModel):
    base_url: str
    api_key: str


# 依赖注入占位符，实际应用中应在 main.py 中覆盖或通过 Request.app.state 获取
def get_repo(request: Request) -> ConfigPresetPGRepo:
    return request.app.state.config_preset_repo

from app.config.crypto import CryptoService

def get_crypto_svc(request: Request) -> CryptoService:
    return request.app.state.crypto_svc


@router.get("", response_model=ResponseModel)
async def get_presets(request: Request, repo: ConfigPresetPGRepo = Depends(get_repo)) -> ResponseModel:
    """获取所有预设列表"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    try:
        presets = await repo.get_all()
        
        resp_data = []
        for p in presets:
            resp_data.append(_to_preset_response(p))
            
        return create_success_response(resp_data, trace_id)
    except Exception as e:
        logger.error(f"获取预设列表失败 error={e}")
        return create_error_response(500, "获取预设列表失败", trace_id)


@router.post("", response_model=ResponseModel)
async def save_preset(
    req: PresetRequest, 
    request: Request, 
    repo: ConfigPresetPGRepo = Depends(get_repo),
    crypto_svc: CryptoService = Depends(get_crypto_svc)
) -> ResponseModel:
    """创建或更新预设"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    if not req.name:
        return create_error_response(400, "预设名称不能为空", trace_id)
        
    try:
        large_config = _encrypt_model_config(req.large_model_config, crypto_svc)
        medium_config = _encrypt_model_config(req.medium_model_config, crypto_svc)
        small_config = _encrypt_model_config(req.small_model_config, crypto_svc)
        
        preset_id = req.id if req.id else generate_string_id()
        
        preset = ApiConfigPreset(
            id=preset_id,
            name=req.name,
            large_model_config=json.loads(large_config),
            medium_model_config=json.loads(medium_config),
            small_model_config=json.loads(small_config),
        )
        
        await repo.save(preset)
        return create_success_response({"id": preset.id}, trace_id)
    except Exception as e:
        logger.error(f"保存预设失败 error={e}")
        return create_error_response(500, "保存预设失败", trace_id)


@router.post("/{id}/activate", response_model=ResponseModel)
async def activate_preset(
    id: str,
    request: Request,
    repo: ConfigPresetPGRepo = Depends(get_repo),
    crypto_svc: CryptoService = Depends(get_crypto_svc)
) -> ResponseModel:
    """激活预设并同步到 Python"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    if not id:
        return create_error_response(400, "缺少预设 ID", trace_id)
        
    try:
        # 1. 更新数据库状态
        await repo.set_active(id)
        
        # 2. 获取激活的预设
        preset = await repo.get_by_id(id)
        if not preset:
            return create_error_response(404, "预设不存在", trace_id)
            
        # 3. 同步到 AI 服务
        from app.config.settings import global_config_container
        
        large_cfg = _decrypt_model_config(json.dumps(preset.large_model_config), crypto_svc)
        medium_cfg = _decrypt_model_config(json.dumps(preset.medium_model_config), crypto_svc)
        small_cfg = _decrypt_model_config(json.dumps(preset.small_model_config), crypto_svc)
        
        await global_config_container.update_preset_config(large_cfg, medium_cfg, small_cfg)
        
        return create_success_response(None, trace_id)
    except Exception as e:
        logger.error(f"激活预设失败 error={e}")
        return create_error_response(500, "激活预设失败", trace_id)


@router.post("/fetch-models", response_model=ResponseModel)
async def fetch_models(req: FetchModelsRequest, request: Request) -> ResponseModel:
    """代理请求目标 API 获取可用模型列表"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    if not req.base_url:
        return create_error_response(400, "Base URL 不能为空", trace_id)
        
    target_url = req.base_url.rstrip("/") + "/models"
    headers = {}
    if req.api_key:
        headers["Authorization"] = f"Bearer {req.api_key}"
        
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, headers=headers, timeout=10.0)
            
        if resp.status_code != 200:
            logger.error(f"目标 API 返回错误 status={resp.status_code} body={resp.text}")
            return create_error_response(500, "目标 API 返回错误", trace_id)
            
        data = resp.json()
        models = []
        for m in data.get("data", []):
            models.append({"id": m.get("id"), "name": m.get("id")})
            
        return create_success_response(models, trace_id)
    except Exception as e:
        logger.error(f"请求目标 API 失败 error={e}")
        return create_error_response(500, "请求目标 API 失败", trace_id)


@router.delete("/{id}", response_model=ResponseModel)
async def delete_preset(id: str, request: Request, repo: ConfigPresetPGRepo = Depends(get_repo)) -> ResponseModel:
    """删除预设"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    
    if not id:
        return create_error_response(400, "缺少预设 ID", trace_id)
        
    try:
        preset = await repo.get_by_id(id)
        if not preset:
            return create_error_response(404, "预设不存在", trace_id)
            
        if preset.is_active:
            return create_error_response(400, "不能删除当前激活的预设", trace_id)
            
        await repo.delete(id)
        return create_success_response(None, trace_id)
    except Exception as e:
        logger.error(f"删除预设失败 error={e}")
        return create_error_response(500, "删除预设失败", trace_id)


# 辅助方法
def _encrypt_model_config(cfg: ModelConfig, crypto_svc: CryptoService) -> str:
    cfg_dict = cfg.model_dump()
    if cfg_dict.get("api_key") and cfg_dict["api_key"] != "********":
        cfg_dict["api_key"] = crypto_svc.encrypt(cfg_dict["api_key"])
    return json.dumps(cfg_dict)

def _decrypt_model_config(json_str: str, crypto_svc: CryptoService) -> dict:
    cfg_dict = json.loads(json_str)
    if cfg_dict.get("api_key"):
        try:
            cfg_dict["api_key"] = crypto_svc.decrypt(cfg_dict["api_key"])
        except Exception:
            pass
            
    return {
        "base_url": cfg_dict.get("base_url", ""),
        "api_key": cfg_dict.get("api_key", ""),
        "model_id": cfg_dict.get("model_id", ""),
        "max_tokens": cfg_dict.get("max_tokens", 0),
        "max_context_tokens": cfg_dict.get("max_context_tokens", 0),
        "temperature": cfg_dict.get("temperature", 0.0),
    }

def _to_preset_response(p: ApiConfigPreset) -> dict:
    large = p.large_model_config
    medium = p.medium_model_config
    small = p.small_model_config
    
    if large.get("api_key"):
        large["api_key"] = "********"
    if medium.get("api_key"):
        medium["api_key"] = "********"
    if small.get("api_key"):
        small["api_key"] = "********"
        
    return {
        "id": p.id,
        "name": p.name,
        "is_active": p.is_active,
        "large_model_config": large,
        "medium_model_config": medium,
        "small_model_config": small,
    }
