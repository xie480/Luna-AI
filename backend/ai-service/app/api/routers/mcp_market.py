"""
MCP 市场 API 路由。

做什么：提供供前端调用的 MCP 市场浏览、搜索、接入和卸载接口。
为什么这样做：前后端分离，为前端提供标准化的数据访问和操作入口。
边界条件：
    - 所有 API 返回完整的 trace_id 用于全链路追踪。
    - 数据库连接不可用时返回 HTTP 503。
    - 传参错误时返回 HTTP 422 详细描述。
"""

import traceback
from typing import Any
import httpx
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


async def _probe_remote_tools(endpoint_url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """通过 MCP Protocol 连接到远程 Server，调用 tools/list 获取工具列表。

    做什么：先发送 initialize 请求建立 MCP Streamable HTTP 会话（如果 Server 支持），
            获取 sessionId 后调用 tools/list 获取工具列表。
            这种两阶段握手兼容有状态（Streamable HTTP）和无状态两种传输模式。
    为什么这样做：部分 MCP Server（如 borealhost.ai）要求客户端先初始化会话，
                 否则 tools/list 返回 "Missing session ID" 错误。
                 两阶段握手确保兼容所有 MCP 传输协议变体。
    边界条件：
        - initialize 失败（Server 不支持）时降级为直接调用 tools/list。
        - 连接超时/失败时返回空列表，不抛出异常。
        - 部分 Server 可能不暴露 tools/list（如纯 Resource Server），
          也返回空列表。
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # ===== 阶段一：initialize 握手（建立会话） =====
            # Streamable HTTP 协议要求先发送 initialize 请求，
            # Server 返回的 result 中可能包含 sessionId。
            # 参考：https://spec.modelcontextprotocol.io/specification/basic/transports/streamable-http
            session_id: str | None = None
            init_payload = {
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "LunaAI",
                        "version": "1.0.0",
                    },
                },
            }
            try:
                init_resp = await client.post(
                    endpoint_url,
                    json=init_payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                init_resp_text = init_resp.text

                # ===== 提前处理认证错误 =====
                # 如果 Server 返回 401/403，说明需要认证才能访问，跳过后续全部探测
                if init_resp.status_code in (401, 403):
                    logger.info(
                        f"远端 MCP 需要认证，跳过工具探测 "
                        f"endpoint={endpoint_url} status_code={init_resp.status_code}"
                    )
                    return []

                # ===== 从响应头中提取 mcp-session-id（优先于 body 解析） =====
                # 注意：必须先提取 sessionId，再尝试解析 body。
                # 因为某些 Server 使用 SSE 传输（Content-Type: text/event-stream），
                # body 不是 JSON 格式，json() 会抛异常。
                session_id = None
                for hk, hv in init_resp.headers.items():
                    if hk.lower() == "mcp-session-id":
                        session_id = hv
                        break

                logger.info(
                    f"远端 MCP initialize 响应 "
                    f"endpoint={endpoint_url} "
                    f"status_code={init_resp.status_code} "
                    f"mcp-session-id={'有' if session_id else '无'} "
                    f"content_type={init_resp.headers.get('content-type', '')} "
                    f"body（前500字符）={init_resp_text[:500]}"
                )

                # ===== 解析 initialize 响应 body =====
                # Server 可能返回两种格式：
                # 1. 纯 JSON：{"jsonrpc":"2.0","result":{...}}
                # 2. SSE 格式：event: message\ndata: {"jsonrpc":"2.0","id":"init-1","result":{...}}
                init_data: dict | None = None
                if init_resp.status_code < 500 and init_resp_text:
                    # 尝试 SSE 格式解析：提取 data: 行中的 JSON
                    if init_resp_text.startswith("event:") or init_resp_text.startswith("data:"):
                        for line in init_resp_text.split("\n"):
                            line = line.strip()
                            if line.startswith("data: ") or line == "data:":
                                data_json = line[5:].strip()
                                if data_json:
                                    try:
                                        init_data = json.loads(data_json)
                                        break
                                    except json.JSONDecodeError:
                                        continue
                    # 如果不是 SSE 格式，尝试直接 JSON 解析
                    if init_data is None:
                        try:
                            init_data = json.loads(init_resp_text)
                        except json.JSONDecodeError:
                            pass

                # ===== 从 result 中提取会话信息 =====
                if init_data and isinstance(init_data, dict) and "error" not in init_data:
                    init_result = init_data.get("result", {})
                    if isinstance(init_result, dict):
                        # 检查 body 中的 _meta.sessionId（某些 Server 放在 body 而非 header）
                        init_meta = init_result.get("_meta", {})
                        if isinstance(init_meta, dict) and not session_id:
                            session_id = init_meta.get("sessionId", None)

                    logger.info(
                        f"远端 MCP initialize 完成 endpoint={endpoint_url} "
                        f"session_id={'有' if session_id else '无（无状态模式）'} "
                        f"server_info={init_result.get('serverInfo', {})}"
                    )
                else:
                    err_detail = init_data.get("error", "解析失败") if init_data else "body非JSON格式"
                    logger.debug(
                        f"远端 MCP initialize 异常响应 "
                        f"endpoint={endpoint_url} detail={err_detail}"
                    )

            except Exception as init_err:
                logger.debug(
                    f"远端 MCP initialize 失败（降级为无状态）"
                    f"endpoint={endpoint_url} error={type(init_err).__name__}: {init_err!s}"
                )

            # ===== 阶段二：调用 tools/list =====
            # 如果初始化拿到了 sessionId，后续请求必须携带
            payload: dict[str, Any] = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": "1",
            }
            if session_id:
                payload["params"] = {
                    "_meta": {"sessionId": session_id},
                }

            # 构建请求头，如果有 sessionId 也放在 header 中（Server 二选一）
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            response = await client.post(
                endpoint_url,
                json=payload,
                headers=headers,
            )

            # 日志：打印原始 HTTP 响应状态码和 body，不论状态码如何都尝试解析
            response_text = response.text
            logger.info(
                f"远端 tools/list HTTP 响应 "
                f"endpoint={endpoint_url} "
                f"status_code={response.status_code} "
                f"body长度={len(response_text)}\n"
                f"原始响应 body（前 3000 字符）:\n{response_text[:3000]}"
            )

            # ===== 解析 tools/list 响应 body =====
            # 兼容两种传输格式：
            # 1. 纯 JSON：{"jsonrpc":"2.0","result":{"tools":[...]},"id":"1"}
            # 2. SSE 格式：event: message\ndata: {"jsonrpc":"2.0","result":{"tools":[...]}}
            tools_data: dict | None = None
            if response_text:
                # 尝试 SSE 格式解析
                if response_text.startswith("event:") or response_text.startswith("data:"):
                    for line in response_text.split("\n"):
                        line = line.strip()
                        if line.startswith("data: ") or line == "data:":
                            data_json = line[5:].strip()
                            if data_json:
                                try:
                                    tools_data = json.loads(data_json)
                                    break
                                except json.JSONDecodeError:
                                    continue
                # 如果不是 SSE 格式，尝试直接 JSON 解析
                if tools_data is None:
                    try:
                        tools_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass

            if tools_data is None:
                logger.debug(f"远端 tools/list 响应解析失败 endpoint={endpoint_url}")
                return []

            # JSON-RPC 响应格式: {"jsonrpc":"2.0","result":{"tools":[...]},"id":"1"}
            if "error" in tools_data:
                logger.debug(
                    f"远端 tools/list 返回错误 "
                    f"endpoint={endpoint_url} "
                    f"error={json.dumps(tools_data['error'], ensure_ascii=False, default=str)}"
                )
                return []

            result = tools_data.get("result", {})
            if not isinstance(result, dict):
                return []

            tools = result.get("tools", [])
            if not isinstance(tools, list):
                return []

            logger.info(
                f"远端 tools/list 探测成功 endpoint={endpoint_url} tool_count={len(tools)}"
            )
            return tools

    except httpx.TimeoutException:
        logger.debug(f"远端 tools/list 超时 endpoint={endpoint_url}")
        return []
    except httpx.RequestError as e:
        logger.debug(f"远端 tools/list 请求失败 endpoint={endpoint_url} error={type(e).__name__}")
        return []
    except json.JSONDecodeError as e:
        logger.debug(f"远端 tools/list JSON 解析失败 endpoint={endpoint_url} error={e}")
        return []
    except Exception as e:
        logger.debug(f"远端 tools/list 未知错误 endpoint={endpoint_url} error={type(e).__name__}: {e}")
        return []


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

    做什么：返回单个 MCP 市场条目的完整元数据，并在首次查看时自动连接
            远程 Server 探测工具能力清单（tools/list），结果缓存到 DB。
    为什么这样做：前端在安装前需要展示完整的 Server 详情和工具列表。
    边界条件：
        - 条目不存在时返回 HTTP 404。
        - 远程探测超时/失败时不阻塞返回，tools 以空列表展示。
        - 已缓存的工具列表不会重复探测（除非 capabilities 为空）。
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

            # 日志：打印完整的数据库查询结果（所有字段），用于诊断字段丢失问题
            logger.info(
                f"MCP 市场详情 DB 原始数据 trace_id={trace_id} id={marketplace_id}\n"
                f"DB 行全部字段:\n{json.dumps(item, ensure_ascii=False, default=str, indent=2)}"
            )

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

            # === 动态探测工具能力 ===
            # 策略：如果 capabilities 为空（首次查看），连接远程 Server 探测；
            # 如果已有缓存，直接使用。允许前端通过 query 参数强制刷新。
            endpoint_url = item.get("endpoint_url", "")
            capabilities = item.get("capabilities") or {}

            # 检查是否需要新探测：capabilities 为空 或 前端请求 force_refresh
            force_refresh = request.query_params.get("force_refresh", "false").lower() == "true"
            need_probe = force_refresh or not capabilities.get("tools")

            raw_tools: list[dict[str, Any]] = []
            if need_probe and endpoint_url:
                logger.info(
                    f"开始动态探测工具能力 trace_id={trace_id} "
                    f"endpoint_url={endpoint_url}"
                )
                raw_tools = await _probe_remote_tools(endpoint_url)

                # 探测成功后写回 DB 缓存（包含 tools + resources + prompts）
                if raw_tools:
                    capabilities["tools"] = raw_tools
                    capabilities["tool_count"] = len(raw_tools)
                    row.capabilities = capabilities
                    row.tool_count = len(raw_tools)
                    row.updated_at = func.now()
                    await session.commit()
                    logger.info(
                        f"工具能力缓存写入完成 trace_id={trace_id} "
                        f"id={marketplace_id} tool_count={len(raw_tools)}"
                    )
            else:
                # 使用已有缓存
                raw_tools = capabilities.get("tools", [])
                if not need_probe and not endpoint_url:
                    logger.debug(f"无 endpoint_url，跳过工具探测 trace_id={trace_id} id={marketplace_id}")
                elif not need_probe:
                    logger.debug(
                        f"使用已缓存工具能力 trace_id={trace_id} "
                        f"id={marketplace_id} tool_count={len(raw_tools)}"
                    )

            # 规范化工具字段
            normalized_tools = []
            for t in raw_tools:
                normalized_tools.append({
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters_schema": t.get("inputSchema", t.get("parameters_schema", {})),
                    "capability_tags": t.get("capability_tags", t.get("tags", [])),
                })
            item["tools"] = normalized_tools
            # 移除原始 capabilities 字段（前端不需要）
            item.pop("capabilities", None)

            # 前端通过可选链兜底所有字段，这里确保最小安全类型
            if not isinstance(item.get("security_flags"), list):
                item["security_flags"] = []
            if not isinstance(item.get("github_stars"), (int, float)):
                item["github_stars"] = 0
            if not isinstance(item.get("trust_score"), (int, float)):
                item["trust_score"] = 0.0
            if not item.get("health_detail"):
                item["health_detail"] = {"latency_ms": 0, "protocol": "unknown", "auth_required": False}

            logger.info(
                f"MCP 市场详情查询完成 trace_id={trace_id} id={marketplace_id} "
                f"tools_count={len(item['tools'])}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": item,
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"MCP 市场详情查询失败 trace_id={trace_id} id={marketplace_id}\n"
            f"异常类型={type(e).__name__} 异常信息={e!s}\n"
            f"完整堆栈:\n{traceback.format_exc()}"
        )
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
        tool_names_to_remove = []
        # 从远程工具池中按 endpoint_url 匹配注销
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


class ToggleInstanceRequest(BaseModel):
    """切换实例启用/禁用请求体。"""
    active: bool = True


@router.post("/api/v1/mcp/market/instance/{instance_id}/toggle")
async def toggle_instance_active(
    instance_id: str,
    body: ToggleInstanceRequest,
    request: Request,
):
    """切换已接入 MCP 实例的启用/禁用状态。

    做什么：设置 mcp_remote_instances 的 is_active 字段为 true 或 false。
            禁用的实例在工具调度时会被跳过。
    为什么这样做：用户在不卸载的前提下临时停用某个远程 MCP。
    边界条件：实例不存在时返回 404。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPRemoteInstance).where(
                    MCPRemoteInstance.id == instance_id,
                    MCPRemoteInstance.user_id == "local_default_user",
                )
            )
            instance = result.scalar_one_or_none()
            if not instance:
                raise HTTPException(status_code=404, detail="实例不存在")

            instance.is_active = body.active
            instance.updated_at = func.now()
            await session.commit()

            logger.info(
                f"MCP 实例启用状态切换完成 trace_id={trace_id} "
                f"instance_id={instance_id} is_active={body.active}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"instance_id": instance_id, "is_active": body.active},
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP 实例状态切换失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"操作失败: {e!s}")


@router.post("/api/v1/mcp/market/instance/{instance_id}/check")
async def health_check_instance(
    instance_id: str,
    request: Request,
):
    """手动触发已接入 MCP 实例的健康检查。

    做什么：连接远程 Endpoint 执行健康检查，更新实例的 health_status、
            last_health_check 和 avg_latency_ms 字段。
    为什么这样做：用户想知道某个远程 MCP 当前是否可用。
    边界条件：实例不存在时返回 404；远程不可达时标记 health_status=offline 不抛异常。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPRemoteInstance).where(
                    MCPRemoteInstance.id == instance_id,
                    MCPRemoteInstance.user_id == "local_default_user",
                )
            )
            instance = result.scalar_one_or_none()
            if not instance:
                raise HTTPException(status_code=404, detail="实例不存在")

            # 执行健康检查
            check_result = await HealthChecker.check_endpoint(instance.endpoint_url)

            # 更新实例健康状态
            instance.health_status = check_result["health_status"]
            instance.avg_latency_ms = check_result["latency_ms"]
            instance.last_health_check = func.now()
            instance.updated_at = func.now()
            await session.commit()

            logger.info(
                f"MCP 实例健康检查完成 trace_id={trace_id} "
                f"instance_id={instance_id} "
                f"health_status={check_result['health_status']} "
                f"latency={check_result['latency_ms']}ms"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "instance_id": instance_id,
                    "health_status": check_result["health_status"],
                    "latency_ms": check_result["latency_ms"],
                    "protocol": check_result["protocol"],
                },
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP 实例健康检查失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {e!s}")


class UpdateInstanceRequest(BaseModel):
    """更新实例配置请求体。"""
    display_name: str | None = None
    auth_config: AuthConfig | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None


@router.post("/api/v1/mcp/market/instance/{instance_id}")
async def update_instance(
    instance_id: str,
    body: UpdateInstanceRequest,
    request: Request,
):
    """更新已接入 MCP 实例的配置。

    做什么：更新 mcp_remote_instances 的 display_name、auth_config、
            timeout_ms、max_retries 等配置字段。
    为什么这样做：用户可以修改接入时的配置（如显示名称、超时时间等）。
    边界条件：实例不存在时返回 404；只更新传入的非空字段。
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session_factory() as session:
            result = await session.execute(
                select(MCPRemoteInstance).where(
                    MCPRemoteInstance.id == instance_id,
                    MCPRemoteInstance.user_id == "local_default_user",
                )
            )
            instance = result.scalar_one_or_none()
            if not instance:
                raise HTTPException(status_code=404, detail="实例不存在")

            # 只更新传入的非空字段
            if body.display_name is not None:
                instance.display_name = body.display_name
            if body.timeout_ms is not None:
                instance.timeout_ms = body.timeout_ms
            if body.max_retries is not None:
                instance.max_retries = body.max_retries
            if body.auth_config is not None:
                auth_crypto = MCPAuthCrypto()
                auth_config_dict = body.auth_config.model_dump()
                auth_encrypted, auth_salt = auth_crypto.encrypt(auth_config_dict)
                instance.auth_config_enc = auth_encrypted
                instance.auth_config_salt = auth_salt
                instance.auth_type = body.auth_config.type

            instance.updated_at = func.now()
            await session.commit()

            logger.info(
                f"MCP 实例配置更新完成 trace_id={trace_id} "
                f"instance_id={instance_id}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {"instance_id": instance_id},
                "trace_id": trace_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP 实例配置更新失败 trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {e!s}")
