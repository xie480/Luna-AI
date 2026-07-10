"""
MCP 本地服务器 API 路由。

做什么：提供供前端调用的本地 MCP 服务器注册、更新、删除和列表查询接口。
         使用独立的 mcp_server_registrations 表存储本地服务器配置。
         服务器的启动命令、参数和环境变量作为独立字段存储，不再嵌套在
         parameters_schema JSONB 中。
为什么这样做：前后端分离，为前端提供标准化的本地服务器管理入口。
             与 mcp_tool_registrations（工具注册表）逻辑解耦，各自独立管理。
边界条件：
    - 所有 API 返回完整的 trace_id 用于全链路追踪。
    - 数据库连接不可用时返回 HTTP 503。
    - 传参错误时返回 HTTP 422 详细描述。
    - name 字段唯一，重复注册返回 409 冲突。
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func

from app.logger import logger
from app.infrastructure.postgres import PostgresClient
from app.repository.models import MCPServerRegistration
from app.utils.snowflake import generate_string_id


router = APIRouter(tags=["MCP Local Server"])


# ============================================================================
# Pydantic 请求/响应模型
# ============================================================================


class LocalServerConfig(BaseModel):
    """注册本地 MCP 服务器的请求体。"""
    name: str
    """服务器唯一名称（在 mcp_server_registrations 中作为 name 字段）。"""
    command: str
    """启动命令（如 node、python 等）。"""
    args: list[str] = []
    """命令参数列表。"""
    env: dict[str, str] = {}
    """环境变量键值对。"""
    description: str = ""
    """服务器描述。"""
    enabled: bool = True
    """是否启用。"""


class BatchRegisterRequest(BaseModel):
    """批量注册本地 MCP 服务器的请求体。"""
    servers: list[LocalServerConfig]
    """待注册的服务器列表。"""


class UpdateLocalServerRequest(BaseModel):
    """更新本地 MCP 服务器配置的请求体。"""
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    description: str | None = None
    enabled: bool | None = None


# ============================================================================
# 辅助函数
# ============================================================================


async def _get_pg_client(request: Request) -> PostgresClient:
    """
    从 app.state 获取 PostgreSQL 客户端。

    做什么：从请求的 app.state 中提取 pg_client 实例。
    为什么这样做：pg_client 在 lifespan 中初始化并注入到 app.state，路由从中获取。
    边界条件：pg_client 不可用时抛 503 并附带中文描述。
    异常行为：pg_client 为 None 时立即抛出 HTTPException(503)。
    """
    pg_client: PostgresClient | None = request.app.state.pg_client
    if not pg_client:
        raise HTTPException(status_code=503, detail="数据库连接不可用，请检查服务状态")
    return pg_client


async def _row_to_local_server_info(row: MCPServerRegistration) -> dict[str, Any]:
    """
    将 MCPServerRegistration ORM 行对象转为 LocalServerInfo 字典。

    做什么：从 ORM 行对象中提取字段，序列化为前端期望的字典格式。
    为什么这样做：ORM 行对象不能直接序列化为 JSON，需要手动转换。
    参数:
        row: MCPServerRegistration ORM 行对象。
    返回:
        dict: 包含 id、name、command、args、env、description、enabled、
              tool_count、endpoint_url、health_status、metadata、
              created_at、updated_at 的字典。
    """
    if row is None:
        return {}

    return {
        "id": row.id,
        "name": row.name,
        "command": row.command,
        "args": row.args or [],
        "env": row.env or {},
        "description": row.description or "",
        "enabled": row.enabled,
        "tool_count": row.tool_count or 0,
        "endpoint_url": row.endpoint_url or "",
        "health_status": row.health_status or "unknown",
        "metadata": row.metadata_ or {},
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


# ============================================================================
# API 端点
# ============================================================================


@router.post("/api/v1/mcp/local/register")
async def register_local_server(
    body: LocalServerConfig,
    request: Request,
):
    """
    注册单个本地 MCP 服务器。

    做什么：
        1. 检查 name 是否已存在，重复则返回 409。
        2. 在 mcp_server_registrations 中创建一条记录。
        3. 将 command/args/env 写入对应的独立字段。
        4. 记录操作日志。
    为什么这样做：用户在前端填写本地 MCP 服务器配置后提交注册。
    边界条件：
        - name 重复时返回 409 冲突。
        - 数据库连接不可用时返回 503。
    参数:
        body: 本地服务器配置（name、command、args、env、description、enabled）。
        request: FastAPI 请求对象，用于获取 pg_client 和 trace_id。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"server_id": "...", "success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session() as session:
        try:
            # Step 1: 检查 name 是否已存在
            existing_result = await session.execute(
                select(MCPServerRegistration).where(
                    MCPServerRegistration.name == body.name,
                ).limit(1)
            )
            if existing_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"本地服务器 '{body.name}' 已经注册，请勿重复操作",
                )

            # Step 2: 创建新记录
            server_id = generate_string_id()
            new_server = MCPServerRegistration(
                id=server_id,
                name=body.name,
                command=body.command,
                args=body.args,
                env=body.env,
                description=body.description,
                enabled=body.enabled,
            )
            session.add(new_server)
            await session.commit()

            logger.info(
                f"本地 MCP 服务器注册完成 "
                f"trace_id={trace_id} server_id={server_id} name={body.name}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "server_id": server_id,
                    "success": True,
                },
                "trace_id": trace_id,
            }

        except HTTPException:
            await session.rollback()
            raise
        except Exception as e:
            await session.rollback()
            logger.error(
                f"本地 MCP 服务器注册失败 "
                f"trace_id={trace_id} name={body.name} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"注册失败: {e!s}")


@router.post("/api/v1/mcp/local/batch-register")
async def batch_register_local_servers(
    body: BatchRegisterRequest,
    request: Request,
):
    """
    批量注册本地 MCP 服务器。

    做什么：遍历 servers 列表，对每个服务器依次执行注册逻辑。
            部分成功时仍返回成功计数和失败详情，不整体回滚。
    为什么这样做：用户可能一次导入多个服务器配置，批量操作更高效。
    边界条件：
        - 列表中某个服务器注册失败不影响其他服务器的注册。
        - 重复名称的服务器被计入 failures 而非成功。
        - 空列表返回 success_count=0, failed_count=0。
    参数:
        body: 包含 servers 列表的请求体。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success_count": N, "failed_count": M, "failures": [...]}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    success_count = 0
    failed_count = 0
    failures: list[dict[str, str]] = []

    for server_config in body.servers:
        async with pg_client.session() as session:
            try:
                # 检查重复
                existing_result = await session.execute(
                    select(MCPServerRegistration).where(
                        MCPServerRegistration.name == server_config.name,
                    ).limit(1)
                )
                if existing_result.scalar_one_or_none():
                    failed_count += 1
                    failures.append({
                        "name": server_config.name,
                        "error": "该服务器已经注册",
                    })
                    continue

                # 创建新记录
                server_id = generate_string_id()
                new_server = MCPServerRegistration(
                    id=server_id,
                    name=server_config.name,
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.env,
                    description=server_config.description,
                    enabled=server_config.enabled,
                )
                session.add(new_server)
                await session.commit()
                success_count += 1

                logger.info(
                    f"批量注册本地服务器成功 "
                    f"trace_id={trace_id} name={server_config.name} "
                    f"server_id={server_id}"
                )

            except Exception as e:
                await session.rollback()
                failed_count += 1
                failures.append({
                    "name": server_config.name,
                    "error": str(e)[:200],  # 截断错误信息避免过长
                })
                logger.warning(
                    f"批量注册本地服务器失败 "
                    f"trace_id={trace_id} name={server_config.name} error={e}"
                )

    logger.info(
        f"批量注册本地服务器完成 "
        f"trace_id={trace_id} success={success_count} failed={failed_count}"
    )

    return {
        "code": 0,
        "msg": "success",
        "data": {
            "success_count": success_count,
            "failed_count": failed_count,
            "failures": failures,
        },
        "trace_id": trace_id,
    }


@router.get("/api/v1/mcp/local/servers")
async def list_local_servers(request: Request):
    """
    获取已注册的本地 MCP 服务器列表。

    做什么：从 mcp_server_registrations 表查询所有记录，
            按创建时间倒序返回服务器信息列表。
    为什么这样做：前端 MCP 面板需要展示已注册的本地服务器列表。
    边界条件：
        - 没有注册记录时返回空列表而非错误。
        - 数据库连接不可用时返回 503。
    参数:
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": [LocalServerInfo, ...], "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    try:
        async with pg_client.session() as session:
            result = await session.execute(
                select(MCPServerRegistration)
                .order_by(MCPServerRegistration.created_at.desc())
            )
            rows = result.scalars().all()

            items = []
            for row in rows:
                item = await _row_to_local_server_info(row)
                items.append(item)

            logger.info(
                f"本地 MCP 服务器列表查询完成 "
                f"trace_id={trace_id} count={len(items)}"
            )

            return {
                "code": 0,
                "msg": "success",
                "data": items,
                "trace_id": trace_id,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"查询本地 MCP 服务器列表失败 "
            f"trace_id={trace_id} error={e}"
        )
        raise HTTPException(status_code=500, detail=f"查询失败: {e!s}")


@router.patch("/api/v1/mcp/local/servers/{server_id}")
async def update_local_server(
    server_id: str,
    body: UpdateLocalServerRequest,
    request: Request,
):
    """
    更新本地 MCP 服务器的配置。

    做什么：根据 server_id 查找对应的记录，
            更新传入的非空字段。只更新传入的非空（非 None）字段，
            未传的字段保持不变。
    为什么这样做：用户可以在前端修改已注册服务器的配置。
    边界条件：
        - server_id 不存在时返回 404。
        - 如果同时更新 name 且新名称已存在，返回 409 冲突。
    参数:
        server_id: 要更新的服务器 ID。
        body: 更新请求体，包含需要更新的字段。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session() as session:
        try:
            # Step 1: 查找现有记录
            result = await session.execute(
                select(MCPServerRegistration).where(
                    MCPServerRegistration.id == server_id,
                ).limit(1)
            )
            server = result.scalar_one_or_none()

            if not server:
                raise HTTPException(
                    status_code=404,
                    detail=f"本地服务器 '{server_id}' 不存在",
                )

            # Step 2: 如果更新 name，检查新名称是否与其他记录冲突
            if body.name is not None and body.name != server.name:
                conflict_result = await session.execute(
                    select(MCPServerRegistration).where(
                        MCPServerRegistration.name == body.name,
                        MCPServerRegistration.id != server_id,
                    ).limit(1)
                )
                if conflict_result.scalar_one_or_none():
                    raise HTTPException(
                        status_code=409,
                        detail=f"名称 '{body.name}' 已被其他本地服务器使用",
                    )
                server.name = body.name

            # Step 3: 更新各字段
            if body.command is not None:
                server.command = body.command
            if body.args is not None:
                server.args = body.args
            if body.env is not None:
                server.env = body.env
            if body.description is not None:
                server.description = body.description
            if body.enabled is not None:
                server.enabled = body.enabled

            # Step 4: 提交更新
            server.updated_at = func.now()
            await session.commit()

            logger.info(
                f"本地 MCP 服务器更新完成 "
                f"trace_id={trace_id} server_id={server_id}"
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
                f"更新本地 MCP 服务器失败 "
                f"trace_id={trace_id} server_id={server_id} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"更新失败: {e!s}")


@router.delete("/api/v1/mcp/local/servers/{server_id}")
async def delete_local_server(
    server_id: str,
    request: Request,
):
    """
    删除本地 MCP 服务器。

    做什么：根据 server_id 查找对应的记录，
            从数据库中永久删除。
    为什么这样做：用户在前端点击删除按钮后移除不再使用的本地服务器。
    边界条件：
        - server_id 不存在时返回 404。
        - 删除操作不可逆，操作前应有前端确认。
    参数:
        server_id: 要删除的服务器 ID。
        request: FastAPI 请求对象。
    返回:
        dict: {"code": 0, "msg": "success", "data": {"success": true}, "trace_id": "..."}
    """
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    pg_client = await _get_pg_client(request)

    async with pg_client.session() as session:
        try:
            # Step 1: 查找记录
            result = await session.execute(
                select(MCPServerRegistration).where(
                    MCPServerRegistration.id == server_id,
                ).limit(1)
            )
            server = result.scalar_one_or_none()

            if not server:
                raise HTTPException(
                    status_code=404,
                    detail=f"本地服务器 '{server_id}' 不存在",
                )

            server_name = server.name

            # Step 2: 删除记录
            await session.delete(server)
            await session.commit()

            logger.info(
                f"本地 MCP 服务器删除完成 "
                f"trace_id={trace_id} server_id={server_id} name={server_name}"
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
                f"删除本地 MCP 服务器失败 "
                f"trace_id={trace_id} server_id={server_id} error={e}"
            )
            raise HTTPException(status_code=500, detail=f"删除失败: {e!s}")
