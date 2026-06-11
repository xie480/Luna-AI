"""
MCP 市场 API 路由。

做什么：提供供前端调用的 MCP 市场浏览、搜索、接入和卸载接口。
为什么这样做：前后端分离，为前端提供标准化的数据访问和操作入口。
边界条件：
    - 所有 API 返回完整的 trace_id 用于全链路追踪。
    - 数据库连接不可用时返回 HTTP 503。
    - 传参错误时返回 HTTP 422 详细描述。
"""

from typing import Any
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
import json

from app.logger import logger
from app.infrastructure.postgres import PostgresClient
from app.mcp.market.capability import CapabilityAnalyzer
from app.mcp.market.crypto import MCPAuthCrypto
from app.mcp.market.health_checker import HealthChecker
from app.mcp.registry import MCPToolRegistry
from app.mcp.types import MCPToolSchema, ToolRiskLevel
from app.repository.mcp_tool_pg import MCPToolPGRepo
from app.repository.models import MCPMarketplace, MCPRemoteInstance, HealthStatus, AuthType
from app.utils.snowflake import generate_string_id


router = APIRouter(tags=["MCP Marketplace"])


class PaginationData(BaseModel):
    """分页数据容器。"""
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class MarketplaceListResponse(BaseModel):
    """市场列表响应。"""
    code: int = 0
    msg: str = "success"
    data: PaginationData
    trace_id: str = ""


class AuthConfig(BaseModel):
    """鉴权配置（用户提交）。"""
    type: str = "none"
    token: str = ""
    key_name: str = ""
    api_key: str = ""


class InstallRemoteMCPRequest(BaseModel):
    """接入远程 MCP 请求体。"""
    endpoint_url: str
    display_name: str
    auth_config: AuthConfig | None = None
    timeout_ms: int = 30000
    max_retries: int = 2


class InstallRemoteMCPResponse(BaseModel):
    """接入远程 MCP 响应。"""
    code: int = 0
    msg: str = "success"
    data: dict[str, Any]
    trace_id: str = ""


async def _get_pg_client(request: Request) -> PostgresClient:
    """从 app.state 获取 PostgreSQL 客户端，不可用时抛 503。"""
    pg_client: PostgresClient | None = request.app.state.pg_client
    if not pg_client:
        raise HTTPException(status_code=503, detail="数据库连接不可用，请检查服务状态")
    return pg_client


async def _get_mcp_pg_repo(request: Request) -> MCPToolPGRepo:
    """从 app.state 构建 MCPToolPGRepo 实例。"""
    pg_client = await _get_pg_client(request)
    async with pg_client.session_factory() as session:
        return MCPToolPGRepo(session)


async def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy ORM 行对象转为字典（处理 JSONB 字段序列化）。"""
    if row is None:
        return {}
    d = {}
    for column in row.__table__.columns:
        val = getattr(row, column.name)
        if isinstance(val, (list, dict)):
            d[column.name] = json.loads(json.dumps(val, default=str))
        else:
            d[column.name] = val
    return d


@router.get("/api/v1/mcp/market/list", response_model=MarketplaceListResponse)
async def list_marketplace(
    request: Request,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数，最大 100"),
    category: str | None = Query(None, description="按分类筛选"),
    tag: str | None = Query(None, description="按标签筛选"),
    health_status: str | None = Query(None, description="按健康状态筛选: online/offline/unknown"),
    sort_by: str = Query("trust_score", regex="^(trust_score|github_stars|install_count|updated_at)$", description="排序字段"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="排序方向: asc/desc"),
) -> MarketplaceListResponse:
    """MCP 市场列表（分页）。

    做什么：返回 mcp_marketplace 表的分页查询结果，支持分类/标签/健康状态筛选
            和多维度排序。
    为什么这样做：前端市场面板需要高效浏览和检索远程 MCP Server。
    边界条件：page=1 为第一页；空结果返回空列表而非错误。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            # 构建计数查询和列表查询的公共 WHERE 条件
            conditions = []
            
            if category and category != "all":
                conditions.append(MCPMarketplace.category == category)
            if health_status:
                conditions.append(MCPMarketplace.health_status == health_status)
            if tag:
                # PostgreSQL ARRAY contains 操作
                conditions.append(func.array_position(MCPMarketplace.tags, text(f"'{tag}'")).isnot(None))

            # 组装基础查询
            base_query = select(MCPMarketplace)
            count_query = select(func.count(MCPMarketplace.id))
            
            if conditions:
                base_query = base_query.where(*conditions)
                count_query = count_query.where(*conditions)

            # 执行计数
            total_result = await session.execute(count_query)
            total = total_result.scalar_one() or 0

            # 执行分页列表查询
            sort_col = getattr(MCPMarketplace, sort_by, MCPMarketplace.trust_score)
            order_func = sort_col.desc() if sort_order == "desc" else sort_col.asc()
            
            offset = (page - 1) * page_size
            list_query = base_query.order_by(order_func).offset(offset).limit(page_size)
            result = await session.execute(list_query)
            rows = result.scalars().all()

            # 转为字典列表
            items = []
            for row in rows:
                d = await _row_to_dict(row)
                # 移除大字段以精简列表响应
                d.pop("original_data", None)
                d.pop("capabilities", None)
                items.append(d)

            logger.info(f"MCP 市场列表查询完成 trace_id={trace_id} total={total} page={page} size={page_size}")

            return MarketplaceListResponse(
                data=PaginationData(items=items, total=total, page=page, page_size=page_size),
                trace_id=trace_id,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP 市场列表查询失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.get("/api/v1/mcp/market/detail/{marketplace_id}")
async def marketplace_detail(
    marketplace_id: str,
    request: Request,
):
    """市场条目详情。

    做什么：返回单个 MCP 市场条目的完整元数据，包括工具能力清单、健康详情
            和用户当前的接入状态。
    为什么这样做：前端在安装前需要展示完整的 Server 详情和工具列表。
    边界条件：条目不存在时返回 HTTP 404。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPMarketplace).where(MCPMarketplace.id == marketplace_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                raise HTTPException(status_code=404, detail="市场条目不存在")

            item = await _row_to_dict(row)

            # 查询用户是否已接入此条目
            instances_result = await session.execute(
                select(MCPRemoteInstance).where(
                    MCPRemoteInstance.marketplace_id == marketplace_id,
                    MCPRemoteInstance.user_id == "local_default_user",
                ).limit(1)
            )
            installed_instance = instances_result.scalar_one_or_none()

            item["is_installed"] = installed_instance is not None
            item["installed_instance_id"] = installed_instance.id if installed_instance else ""

            return {
                "code": 0,
                "msg": "success",
                "data": item,
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP 市场详情查询失败 trace_id={trace_id} id={marketplace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.post("/api/v1/mcp/market/install/{marketplace_id}", response_model=InstallRemoteMCPResponse)
async def install_remote_mcp(
    marketplace_id: str,
    body: InstallRemoteMCPRequest,
    request: Request,
) -> InstallRemoteMCPResponse:
    """接入远程 MCP（一键接入）。

    做什么：用户在前端点击"接入"后，后端执行以下步骤：
            1. 从 mcp_marketplace 获取 Server 元数据。
            2. 如果已接入则返回错误（幂等检查）。
            3. 连接远程 Endpoint 验证可达性。
            4. 调用 MCPToolRegistry 注册工具（source=remote）。
            5. 写入 mcp_remote_instances 持久化配置。
            6. 加密存储鉴权信息。
            7. 标记市场条目的 install_count +1。
    为什么这样做：用户不需要关心远程 MCP 的技术细节，一键完成接入。
    边界条件：
        - 同一 Server 重复接入时返回 409 冲突。
        - 远程 Endpoint 不可达时仍允许注册但标记 health=unknown。
        - auth_config.type=none 时跳过加密流程。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        # Step 1: 查询市场条目
        result = await session.execute(
            select(MCPMarketplace).where(MCPMarketplace.id == marketplace_id)
        )
        marketplace_item = result.scalar_one_or_none()
        if not marketplace_item:
            raise HTTPException(status_code=404, detail="市场条目不存在")

        # Step 2: 幂等检查 - 是否已接入
        existing_result = await session.execute(
            select(MCPRemoteInstance).where(
                MCPRemoteInstance.marketplace_id == marketplace_id,
                MCPRemoteInstance.user_id == "local_default_user",
            ).limit(1)
        )
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="该 MCP 已经接入，请勿重复操作")

        # Step 3: 解析能力清单
        capabilities = marketplace_item.capabilities or {}
        tools = capabilities.get("tools", [])

        # Step 4: 加密鉴权凭证
        auth_encrypted = ""
        auth_salt = ""
        auth_type = AuthType.NONE.value
        if body.auth_config and body.auth_config.type != AuthType.NONE.value:
            auth_crypto = MCPAuthCrypto()
            auth_config_dict = body.auth_config.model_dump()
            auth_encrypted, auth_salt = auth_crypto.encrypt(auth_config_dict)
            auth_type = body.auth_config.type

        # Step 5: 验证远程 Endpoint 可达性
        check_result = await HealthChecker.check_endpoint(
            body.endpoint_url or marketplace_item.endpoint_url
        )
        health_status_value = check_result["health_status"]

        # Step 6: 注册到 MCPToolRegistry
        registry = MCPToolRegistry()
        endpoint_url = body.endpoint_url or marketplace_item.endpoint_url
        registered_tool_names = []
        for tool_def in tools:
            tool_name = tool_def.get("name", "")
            if not tool_name:
                continue
            schema = CapabilityAnalyzer.build_tool_schema_from_remote(
                tool_def=tool_def,
                server_category=marketplace_item.category or "",
                endpoint_url=endpoint_url,
            )
            registry.register_remote(
                name=tool_name,
                schema=schema,
                endpoint_url=endpoint_url,
            )
            registered_tool_names.append(tool_name)

        # Step 7: 持久化远程实例配置
        instance_id = generate_string_id()
        display_name = body.display_name or marketplace_item.display_name or marketplace_item.name

        new_instance = MCPRemoteInstance(
            id=instance_id,
            marketplace_id=marketplace_id,
            user_id="local_default_user",
            display_name=display_name,
            endpoint_url=endpoint_url,
            auth_type=auth_type,
            auth_config_enc=auth_encrypted,
            auth_config_salt=auth_salt,
            proxy_enabled=True,
            timeout_ms=body.timeout_ms,
            max_retries=body.max_retries,
            is_active=True,
            health_status=health_status_value,
        )
        session.add(new_instance)

        # Step 8: 更新市场统计
        marketplace_item.install_count = (marketplace_item.install_count or 0) + 1
        marketplace_item.updated_at = func.now()

        # Step 9: 持久化工具注册到 PG
        mcp_pg_repo = MCPToolPGRepo(session)
        await registry.persist_to_pg(mcp_pg_repo)

        await session.commit()

        logger.info(
            f"远程 MCP 接入完成 trace_id={trace_id} instance_id={instance_id} "
            f"marketplace_id={marketplace_id} tool_count={len(tools)}"
        )

        return InstallRemoteMCPResponse(
            data={
                "instance_id": instance_id,
                "marketplace_id": marketplace_id,
                "display_name": display_name,
                "health_status": health_status_value,
                "tool_count": len(tools),
                "tool_names": registered_tool_names,
                "registered": True,
            },
            trace_id=trace_id,
        )


@router.get("/api/v1/mcp/market/installed")
async def list_installed_mcp(request: Request):
    """获取已接入的 MCP 实例列表。"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPRemoteInstance)
                .where(MCPRemoteInstance.user_id == "local_default_user")
                .order_by(MCPRemoteInstance.created_at.desc())
            )
            rows = result.scalars().all()
            items = [await _row_to_dict(r) for r in rows]
            return {"code": 0, "msg": "success", "data": items, "trace_id": trace_id}
    except Exception as e:
        logger.error(f"查询已接入 MCP 实例失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.post("/api/v1/mcp/market/uninstall/{instance_id}")
async def uninstall_remote_mcp(instance_id: str, request: Request):
    """卸载已接入的 MCP 实例。

    做什么：从数据库删除远程实例记录，从 MCPToolRegistry 注销所有关联工具，
            更新市场条目的安装计数。
    为什么这样做：用户需要能移除不再使用的远程 MCP 接入。
    边界条件：实例不存在时返回 404。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session_factory() as session:
        # Step 1: 查询实例
        result = await session.execute(
            select(MCPRemoteInstance).where(
                MCPRemoteInstance.id == instance_id,
                MCPRemoteInstance.user_id == "local_default_user",
            )
        )
        instance = result.scalar_one_or_none()
        if not instance:
            raise HTTPException(status_code=404, detail="实例不存在")

        marketplace_id = instance.marketplace_id

        # Step 2: 从 MCPToolRegistry 注销关联工具
        registry = MCPToolRegistry()
        # 查找远程工具池中关联到此实例的工具
        # 由于目前注册工具没有直接关联 instance_id，我们使用 endpoint_url 匹配
        endpoint_url = instance.endpoint_url
        unregistered_count = 0
        # 从远程工具池中按 endpoint_url 匹配注销
        # 注意: registry 内部是 dict，无法直接按 endpoint_url 遍历
        # 使用 list_tools 获取所有工具名
        if hasattr(registry, '_remote_tools'):
            tool_names_to_remove = [
                name for name, rt in registry._remote_tools.items()
                if rt.schema and rt.schema.endpoint_url == endpoint_url
            ]
            for name in tool_names_to_remove:
                try:
                    registry.unregister(name)
                    unregistered_count += 1
                except KeyError:
                    pass

        # Step 3: 从 PG 删除工具注册
        mcp_pg_repo = MCPToolPGRepo(session)
        for name in tool_names_to_remove:
            await mcp_pg_repo.delete(name)

        # Step 4: 删除远程实例记录
        await session.delete(instance)

        # Step 5: 更新市场计数
        market_result = await session.execute(
            select(MCPMarketplace).where(MCPMarketplace.id == marketplace_id)
        )
        market_item = market_result.scalar_one_or_none()
        if market_item and market_item.install_count > 0:
            market_item.install_count -= 1

        await session.commit()

        logger.info(
            f"远程 MCP 卸载完成 trace_id={trace_id} instance_id={instance_id} "
            f"unregistered_tools={unregistered_count}"
        )

        return {
            "code": 0,
            "msg": "success",
            "data": {"unregistered_tools": unregistered_count},
            "trace_id": trace_id,
        }


@router.get("/api/v1/mcp/market/search", response_model=MarketplaceListResponse)
async def search_marketplace(
    request: Request,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """全文搜索 MCP 市场（支持能力级语义搜索）。

    做什么：对 mcp_marketplace 的 name 和 description 字段执行 PostgreSQL
            全文检索（to_tsvector/plainto_tsquery/ts_rank），按相关性得分排序。
    为什么这样做：用户搜索"数据库"时真正想找的是能执行 SQL 的工具，
                需要检索到工具级别的能力描述。
    边界条件：全表 PG FTS 扫描，数据量大时可考虑 GIN 索引加速。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            # 使用 PostgreSQL FTS 全文检索
            offset = (page - 1) * page_size

            # 构建搜索条件：tsvector on name || ' ' || description
            search_query = text("""
                SELECT * FROM mcp_marketplace
                WHERE to_tsvector('simple',
                    COALESCE(name, '') || ' ' ||
                    COALESCE(display_name, '') || ' ' ||
                    COALESCE(description, '')
                ) @@ plainto_tsquery('simple', :query)
                ORDER BY ts_rank(
                    to_tsvector('simple',
                        COALESCE(name, '') || ' ' ||
                        COALESCE(display_name, '') || ' ' ||
                        COALESCE(description, '')
                    ),
                    plainto_tsquery('simple', :query)
                ) DESC
                LIMIT :limit OFFSET :offset
            """)

            count_query = text("""
                SELECT COUNT(*) FROM mcp_marketplace
                WHERE to_tsvector('simple',
                    COALESCE(name, '') || ' ' ||
                    COALESCE(display_name, '') || ' ' ||
                    COALESCE(description, '')
                ) @@ plainto_tsquery('simple', :query)
            """)

            params = {"query": q, "limit": page_size, "offset": offset}

            total_result = await session.execute(count_query, {"query": q})
            total = total_result.scalar_one() or 0

            result = await session.execute(search_query, params)
            rows = result.all()

            items = []
            for row in rows:
                d = dict(row._mapping)
                items.append(d)

            logger.info(
                f"MCP 市场搜索完成 trace_id={trace_id} query='{q}' total={total} hits={len(items)}"
            )

            return MarketplaceListResponse(
                data=PaginationData(items=items, total=total, page=page, page_size=page_size),
                trace_id=trace_id,
            )
    except Exception as e:
        logger.error(f"MCP 市场搜索失败 trace_id={trace_id} query='{q}' error={e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e!s}")


@router.get("/api/v1/mcp/market/categories")
async def list_categories(request: Request):
    """获取所有市场分类。"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPMarketplace.category, func.count(MCPMarketplace.id).label("count"))
                .group_by(MCPMarketplace.category)
                .order_by(MCPMarketplace.category)
            )
            rows = result.all()
            categories = [
                {"category": row.category or "uncategorized", "count": row.count}
                for row in rows
            ]
            return {"code": 0, "msg": "success", "data": categories, "trace_id": trace_id}
    except Exception as e:
        logger.error(f"查询分类失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.get("/api/v1/mcp/market/trending")
async def trending_marketplace(
    request: Request,
    limit: int = Query(10, ge=1, le=50, description="返回条数"),
):
    """热门/推荐 MCP 列表。"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPMarketplace)
                .where(MCPMarketplace.health_status == HealthStatus.ONLINE.value)
                .order_by(
                    MCPMarketplace.trust_score.desc(),
                    MCPMarketplace.install_count.desc(),
                )
                .limit(limit)
            )
            rows = result.scalars().all()
            items = [await _row_to_dict(r) for r in rows]
            return {"code": 0, "msg": "success", "data": items, "trace_id": trace_id}
    except Exception as e:
        logger.error(f"查询热门 MCP 失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")
