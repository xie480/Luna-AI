"""
MCP 市场 API 路由。

做什么：提供供前端调用的 MCP 市场浏览、搜索、接入和卸载接口。
为什么这样做：前后端分离，为前端提供标准化的数据访问和操作入口。
"""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.logger import logger
from app.mcp.market.capability import CapabilityAnalyzer
from app.mcp.market.crypto import MCPAuthCrypto
from app.mcp.market.health_checker import HealthChecker
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import MCPToolSchema, ToolRiskLevel
from app.utils.snowflake import generate_string_id


router = APIRouter(tags=["MCP Marketplace"])


class PaginationData(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int

class MarketplaceListResponse(BaseModel):
    code: int = 0
    msg: str = "success"
    data: PaginationData
    trace_id: str

class AuthConfig(BaseModel):
    type: str = "none"
    token: str = ""
    key_name: str = ""
    api_key: str = ""

class InstallRemoteMCPRequest(BaseModel):
    endpoint_url: str
    display_name: str
    auth_config: AuthConfig | None = None
    timeout_ms: int = 30000
    max_retries: int = 2

class InstallRemoteMCPResponse(BaseModel):
    code: int = 0
    msg: str = "success"
    data: dict[str, Any]
    trace_id: str


@router.get("/api/v1/mcp/market/list", response_model=MarketplaceListResponse)
async def list_marketplace(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    tag: str | None = Query(None),
    health_status: str | None = Query(None),
    sort_by: str = Query("trust_score", regex="^(trust_score|github_stars|install_count|updated_at)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
) -> MarketplaceListResponse:
    """MCP 市场列表（分页）。"""
    trace_id = request.headers.get("X-Trace-ID", "")
    pg_client = request.app.state.pg_client
    
    if not pg_client:
        raise HTTPException(status_code=503, detail="Database connection not available")

    # 构建基础查询
    query = "SELECT * FROM mcp_marketplace WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM mcp_marketplace WHERE 1=1"
    params = []
    
    if category and category != "all":
        query += f" AND category = ${len(params) + 1}"
        count_query += f" AND category = ${len(params) + 1}"
        params.append(category)
        
    if health_status:
        query += f" AND health_status = ${len(params) + 1}"
        count_query += f" AND health_status = ${len(params) + 1}"
        params.append(health_status)

    if tag:
        # PostgreSQL Array contains
        query += f" AND ${len(params) + 1} = ANY(tags)"
        count_query += f" AND ${len(params) + 1} = ANY(tags)"
        params.append(tag)
        
    query += f" ORDER BY {sort_by} {sort_order.upper()}"
    query += f" LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    
    limit = page_size
    offset = (page - 1) * page_size
    
    try:
        from sqlalchemy import text
        async with pg_client.engine.begin() as conn:
            # PostgreSQL requires bound parameters like :1, or text().bindparams()
            # Let's use string formatting carefully for simple queries, or text() 
            # For simplicity in this mock, we use a basic SQL construction
            # In a real app we'd use SQLAlchemy Core or ORM.
            
            # Using SQLAlchemy Core style:
            # Let's just fetch all and filter in python for this MVP if needed, or use proper text()
            pass
            
        # Simplified response for the plan
        return MarketplaceListResponse(
            data=PaginationData(
                items=[],
                total=0,
                page=page,
                page_size=page_size
            ),
            trace_id=trace_id
        )
    except Exception as e:
        logger.error(f"Failed to list marketplace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/mcp/market/install/{marketplace_id}", response_model=InstallRemoteMCPResponse)
async def install_remote_mcp(
    marketplace_id: str,
    body: InstallRemoteMCPRequest,
    request: Request,
) -> InstallRemoteMCPResponse:
    """接入远程 MCP（一键接入）。"""
    trace_id = request.headers.get("X-Trace-ID", "")
    pg_client = request.app.state.pg_client
    
    if not pg_client:
        raise HTTPException(status_code=503, detail="Database connection not available")

    # 1. 查询市场条目 (这里伪代码略去实际 DB 查，假设找到)
    # marketplace_item = ...
    
    # 2. 检查是否已接入
    
    # 3. 解析能力清单
    tools = [] # 从 marketplace_item["capabilities"] 获取
    
    # 4. 加密鉴权凭证
    crypto: MCPAuthCrypto = request.app.state.crypto_svc # 注意要确保 crypto_svc 类型
    auth_encrypted = ""
    auth_salt = ""
    if body.auth_config and body.auth_config.type != "none":
        # 实际代码需要从 app.state 中获取一个可用的 crypto 实例
        auth_crypto = MCPAuthCrypto()
        auth_encrypted, auth_salt = auth_crypto.encrypt(body.auth_config.dict())

    # 5. 验证可达性
    check_result = await HealthChecker.check_endpoint(body.endpoint_url)
    health_status = check_result["health_status"]

    # 6. 注册到 MCPToolRegistry
    registry = MCPToolRegistry()
    for tool_def in tools:
        schema = MCPToolSchema(
            name=tool_def["name"],
            description=tool_def.get("description", ""),
            parameters_schema=tool_def.get("parameters_schema", {}),
            risk_level=ToolRiskLevel.L0,
            tags=tool_def.get("tags", []),
            category="custom",
            core_purpose=tool_def.get("core_purpose", ""),
            final_deliverable=tool_def.get("final_deliverable", ""),
            source="remote",
            endpoint_url=body.endpoint_url,
        )
        registry.register_remote(
            name=tool_def["name"],
            schema=schema,
            endpoint_url=body.endpoint_url,
        )

    # 7. 持久化远程实例配置 (SQL 写入)
    instance_id = generate_string_id()
    
    # 8. 持久化注册到 PG
    pg_repo = request.app.state.pg_repo # 假设这是 MCPToolPGRepo，实际需要在 state 注入
    # await registry.persist_to_pg(pg_repo)
    
    logger.info(f"远程 MCP 接入完成 trace_id={trace_id} instance_id={instance_id} marketplace_id={marketplace_id}")

    return InstallRemoteMCPResponse(
        data={
            "instance_id": instance_id,
            "health_status": health_status,
            "tool_count": len(tools),
            "tool_names": [t.get("name") for t in tools],
        },
        trace_id=trace_id
    )

@router.get("/api/v1/mcp/market/installed")
async def list_installed_mcp(request: Request):
    """获取已接入的 MCP 实例。"""
    return {"code": 0, "msg": "success", "data": [], "trace_id": request.headers.get("X-Trace-ID", "")}

@router.post("/api/v1/mcp/market/uninstall/{instance_id}")
async def uninstall_remote_mcp(instance_id: str, request: Request):
    """卸载已接入的 MCP 实例。"""
    # 1. 从 DB 删除 mcp_remote_instances
    # 2. 从 MCPToolRegistry 注销相关工具
    # 3. 更新 mcp_marketplace install_count
    return {"code": 0, "msg": "success", "data": None, "trace_id": request.headers.get("X-Trace-ID", "")}

@router.get("/api/v1/mcp/market/search", response_model=MarketplaceListResponse)
async def search_marketplace(
    request: Request,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """全文搜索 MCP 市场（支持能力级语义搜索）。"""
    trace_id = request.headers.get("X-Trace-ID", "")
    return MarketplaceListResponse(
        data=PaginationData(
            items=[],
            total=0,
            page=page,
            page_size=page_size
        ),
        trace_id=trace_id
    )

@router.get("/api/v1/mcp/market/detail/{marketplace_id}")
async def marketplace_detail(marketplace_id: str, request: Request):
    """市场条目详情。"""
    return {"code": 0, "msg": "success", "data": {}, "trace_id": request.headers.get("X-Trace-ID", "")}
