"""
MCP 工具配置 API 路由。

做什么：提供供前端调用的 MCP 工具配置 CRUD 接口。
        前端在 Skill 面板中查看技能详情时，展开工具列表，
        每个工具条目旁有一个"配置"按钮，点击弹出配置模态框。
        此路由提供配置的读取、保存和删除能力。
为什么这样做：工具配置不应与系统环境变量（.env）耦合，用户应在
             前端面板中独立设置每个工具的专有参数。
边界条件：
    - tool_name 对应 MCPToolRegistry 中的工具名称。
    - 配置数据为键值对格式，不同工具有不同的配置 Schema。
    - 配置保存后自动刷新 ToolConfigManager 的内存缓存。
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config.tool_config_manager import ToolConfigManager
from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.tool_config_pg import ToolConfigPGRepo
from app.utils.snowflake import generate_string_id


router = APIRouter(tags=["MCP Tool Config"])


# ============================================================================
# Pydantic 请求/响应模型
# ============================================================================


class ToolConfigSchema(BaseModel):
    """工具配置对象。"""
    tool_name: str = ""
    """工具名称，对应注册中心中的工具名称。"""
    config_data: dict[str, Any] = {}
    """配置键值对。不同工具有不同的配置字段。"""
    description: str = ""
    """配置说明或备注。"""


class ToolConfigResponse(BaseModel):
    """工具配置响应。"""
    tool_name: str
    config_data: dict[str, Any]
    status: str
    description: str
    created_at: str = ""
    updated_at: str = ""


# 各工具支持的配置字段描述
# 供前端在"配置"对话框中展示字段说明和输入提示
TOOL_CONFIG_SCHEMAS: dict[str, dict[str, Any]] = {
    "web_search": {
        "title": "Web Search 搜索工具配置",
        "description": "配置 SearXNG 元搜索引擎的连接参数与并发搜索策略。",
        "fields": [
            {
                "key": "base_url",
                "label": "SearXNG 实例地址",
                "type": "text",
                "required": True,
                "placeholder": "http://localhost:8888",
                "description": "SearXNG 实例的基础 URL（必填）。例如：http://localhost:8888",
            },
            {
                "key": "timeout",
                "label": "搜索超时时间（秒）",
                "type": "number",
                "required": False,
                "default": "15",
                "placeholder": "15",
                "description": "搜索请求超时时间，单位秒。默认：15",
            },
            {
                "key": "concurrent_requests",
                "label": "并发请求数量",
                "type": "number",
                "required": False,
                "default": "3",
                "placeholder": "3",
                "description": "同时发送的搜索请求组数量，也是 query 外层数组的长度。范围：1-10。默认：3",
            },
            {
                "key": "results_per_request",
                "label": "每请求结果数",
                "type": "number",
                "required": False,
                "default": "10",
                "placeholder": "10",
                "description": "每组请求期望收集的结果条数。范围：1-50。默认：10",
            },
            {
                "key": "max_url_fetch_length",
                "label": "输出内容长度上限",
                "type": "number",
                "required": False,
                "default": "8192",
                "placeholder": "8192",
                "description": "格式化输出结果的最大字符数。默认：8192",
            },
            {
                "key": "safe_search_level",
                "label": "安全搜索级别",
                "type": "number",
                "required": False,
                "default": "1",
                "placeholder": "1",
                "description": "安全搜索级别。0=关闭，1=中等，2=严格。默认：1",
            },
        ],
    },
}


# ============================================================================
# 辅助函数
# ============================================================================


async def _get_pg_client(request: Request) -> PostgresClient:
    """
    从 app.state 获取 PostgreSQL 客户端。

    做什么：从请求的 app.state 中提取 pg_client 实例。
    为什么这样做：pg_client 在 lifespan 中初始化并注入到 app.state，路由从中获取。
    边界条件：pg_client 不可用时抛 503 并附带中文描述。
    """
    pg_client: PostgresClient | None = request.app.state.pg_client
    if not pg_client:
        raise HTTPException(status_code=503, detail="数据库连接不可用，请检查服务状态")
    return pg_client


async def _get_tool_config_repo(request: Request) -> ToolConfigPGRepo:
    """
    获取 ToolConfigPGRepo 实例。

    做什么：从 pg_client 创建会话并构造仓库实例。
    为什么这样做：每次请求创建独立的会话，避免并发问题。
    """
    pg_client = await _get_pg_client(request)
    session = pg_client.session_factory()
    return ToolConfigPGRepo(session)


# ============================================================================
# API 端点
# ============================================================================


@router.get("/api/v1/mcp/tool-configs")
async def list_tool_configs(request: Request):
    """
    获取所有工具配置列表。

    做什么：从 tool_configs 表查询所有 ACTIVE 状态的配置记录。
    为什么这样做：前端在配置管理页面需要展示所有已配置的工具。
    返回:
        dict: {"code": 0, "msg": "success", "data": [ToolConfigResponse, ...], "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            repo = ToolConfigPGRepo(session)
            configs = await repo.load_all()

            logger.info(
                f"工具配置列表查询完成 "
                f"trace_id={trace_id} count={len(configs)}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": configs,
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询工具配置列表失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.get("/api/v1/mcp/tool-configs/{tool_name}")
async def get_tool_config(tool_name: str, request: Request):
    """
    获取指定工具的配置。

    做什么：根据工具名称查询配置记录，同时返回该工具的配置字段 Schema。
    为什么这样做：前端配置对话框需要展示对应的字段定义。
    参数:
        tool_name: 工具名称，如 "web_search"。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"config": ..., "schema": ...}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            repo = ToolConfigPGRepo(session)
            config = await repo.get_by_tool_name(tool_name)

            # 获取该工具的配置字段 Schema
            field_schema = TOOL_CONFIG_SCHEMAS.get(tool_name, None)

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "config": config or {
                        "tool_name": tool_name,
                        "config_data": {},
                        "status": "INACTIVE",
                        "description": "",
                    },
                    "schema": field_schema,
                },
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询工具配置失败 trace_id={trace_id} tool_name={tool_name} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.get("/api/v1/mcp/tool-configs/{tool_name}/schema")
async def get_tool_config_schema(tool_name: str, request: Request):
    """
    获取指定工具的配置字段 Schema（无实际配置数据）。

    做什么：返回该工具支持的配置字段定义，供前端动态渲染配置表单。
    为什么这样做：前端在没有配置时也能展示配置表单的字段定义。
    参数:
        tool_name: 工具名称。
    返回:
        dict: {"code": 0, "msg": "success", "data": schema, "trace_id": "..."}
        如果该工具没有定义配置 Schema，data 为 null。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    field_schema = TOOL_CONFIG_SCHEMAS.get(tool_name, None)

    return {
        "code": 0,
        "msg": "success",
        "data": field_schema,
        "trace_id": trace_id,
    }


@router.post("/api/v1/mcp/tool-configs/{tool_name}")
async def save_tool_config(
    tool_name: str,
    body: ToolConfigSchema,
    request: Request,
):
    """
    保存工具配置。

    做什么：Upsert 指定工具的配置数据，保存后自动刷新 ToolConfigManager 缓存。
    为什么这样做：用户在前端配置对话框中填写字段后点击保存。
    参数:
        tool_name: 工具名称。
        body: 包含 config_data 和 description 的配置对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        try:
            repo = ToolConfigPGRepo(session)
            success = await repo.upsert(
                tool_name=tool_name,
                config_data=body.config_data,
                description=body.description,
            )

            if not success:
                raise HTTPException(
                    status_code=500,
                    detail=f"保存工具配置 '{tool_name}' 失败",
                )

            # 刷新内存缓存
            config_mgr = ToolConfigManager()
            config_mgr.reload_single(tool_name, body.config_data)

            logger.info(
                f"工具配置保存完成 "
                f"trace_id={trace_id} tool_name={tool_name} "
                f"config_keys={list(body.config_data.keys())}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"success": True},
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"保存工具配置失败 "
                f"trace_id={trace_id} tool_name={tool_name} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"保存失败: {e!s}")


@router.delete("/api/v1/mcp/tool-configs/{tool_name}")
async def delete_tool_config(tool_name: str, request: Request):
    """
    删除工具配置（软删除）。

    做什么：将指定工具配置的状态设为 INACTIVE，并清理内存缓存。
    为什么这样做：用户在前端点击"清除配置"时调用。
    参数:
        tool_name: 工具名称。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        try:
            repo = ToolConfigPGRepo(session)
            success = await repo.delete(tool_name)

            if not success:
                raise HTTPException(
                    status_code=404,
                    detail=f"工具 '{tool_name}' 的配置不存在",
                )

            # 清理内存缓存
            config_mgr = ToolConfigManager()
            config_mgr.remove(tool_name)

            logger.info(
                f"工具配置删除完成 "
                f"trace_id={trace_id} tool_name={tool_name}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"success": True},
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"删除工具配置失败 "
                f"trace_id={trace_id} tool_name={tool_name} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"删除失败: {e!s}")
