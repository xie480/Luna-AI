import asyncio
from typing import Dict, Any, List

from app.logger import logger
from app.mcp.server_manager import MCPServerManager, MCPServerConfigModel
from app.mcp.connection_manager import McpConnectionManager
from app.mcp.skill_registry import SkillRegistry
from app.infrastructure.postgres import PostgresClient
from app.repository.models import MCPToolRegistration
from app.utils.snowflake import generate_string_id


class DiscoverySyncEngine:
    """
    外部 MCP 发现与同步引擎。
    
    做什么：实现 Server -> Tool 的拉取与持久化。
    为什么这样做：外部工具是通过注册的 Server 提供的。系统需要通过
                MCPConnectionManager 建立连接，然后调用 session.list_tools() 
                获取可用工具并更新数据库。
    """
    _instance = None

    def __init__(self):
        self._manager = MCPServerManager.get_instance()
        self._connection_manager = McpConnectionManager.get_instance()
        self._skill_registry = SkillRegistry()

    @classmethod
    def get_instance(cls) -> "DiscoverySyncEngine":
        if cls._instance is None:
            cls._instance = DiscoverySyncEngine()
        return cls._instance

    async def sync_everything(self, pg_client: PostgresClient):
        """执行全量同步发现，供启动和定时任务调用"""
        logger.info("开始执行 MCP 全量发现 (Servers -> Tools)")
        servers = self._manager.get_all_active_servers()
        
        for server in servers:
            try:
                await self.sync_server_tools(pg_client, server)
            except Exception as e:
                logger.error(f"同步 Server {server.server_id} 异常: {e}", exc_info=True)
                
        # 刷新本地缓存供 Agent 路由使用
        async with pg_client.session() as session:
            try:
                await self._skill_registry.load_from_pg(session)
            except Exception as e:
                logger.warning(f"全量同步后刷新 SkillRegistry 缓存失败: {e}", exc_info=True)

    def _map_risk_level(self, tool_def: Any) -> str:
        """动态映射风险等级。"""
        risk_level = "L1"
        annotations = tool_def.get("annotations", {})
        read_only_hint = tool_def.get("readOnlyHint") or annotations.get("readOnlyHint", False)
        destructive_hint = tool_def.get("destructiveHint") or annotations.get("destructiveHint", False)
        
        if destructive_hint:
            risk_level = "L2"
        elif read_only_hint:
            risk_level = "L0"
            
        return risk_level

    async def sync_server_tools(self, pg_client: PostgresClient, server: MCPServerConfigModel):
        """同步指定 Server 的工具。"""
        logger.info(f"Syncing tools for server: {server.server_id} at {server.endpoint_url}")
        if not server.endpoint_url:
            return
            
        session = await self._connection_manager.get_or_create_session(server.server_id)
        if not session:
            logger.warning(f"无法建立与 Server {server.server_id} 的连接。")
            return
            
        try:
            tools_response = await session.list_tools()
        except Exception as e:
            logger.error(f"Failed to list tools from server {server.server_id}: {e}", exc_info=True)
            return
            
        if not tools_response or not tools_response.tools:
            logger.warning(f"No tools found for server {server.server_id}.")
            return
            
        tools = tools_response.tools

        tool_names_synced = []
        async with pg_client.session() as db_session:
            from sqlalchemy import select
            
            for tool_def in tools:
                raw_name = tool_def.name
                if not raw_name:
                    continue
                    
                tool_name = f"{server.namespace}.{raw_name}"
                
                # 黑白名单过滤
                if raw_name in server.deny_tools:
                    continue
                if "*" not in server.allow_tools and raw_name not in server.allow_tools:
                    continue

                description = tool_def.description or ""
                # inputSchema in sdk is a dict
                input_schema = tool_def.inputSchema or {}
                risk_level = self._map_risk_level(tool_def)
                
                stmt = select(MCPToolRegistration).where(MCPToolRegistration.name == tool_name)
                result = await db_session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    existing.description = description
                    existing.parameters_schema = input_schema
                    existing.risk_level = risk_level
                    existing.enabled = True
                    existing.is_external = True
                    existing.server_id = server.server_id
                else:
                    new_tool = MCPToolRegistration(
                        id=generate_string_id(),
                        name=tool_name,
                        description=description,
                        parameters_schema=input_schema,
                        risk_level=risk_level,
                        enabled=True,
                        is_external=True,
                        server_id=server.server_id,
                        source="remote_discovery"
                    )
                    db_session.add(new_tool)
                    
                tool_names_synced.append(tool_name)
                
            await db_session.commit()
            
        logger.info(f"Synced {len(tool_names_synced)} tools from {server.server_id}.")

    async def start_background_sync(self, pg_client: PostgresClient, interval_seconds: int = 3600):
        """
        启动后台定时同步任务。
        """
        logger.info(f"Starting background discovery sync with interval {interval_seconds}s")
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.sync_everything(pg_client)
            except Exception as e:
                logger.error(f"Error in background sync loop: {e}", exc_info=True)