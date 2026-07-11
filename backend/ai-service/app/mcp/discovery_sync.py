import asyncio
from typing import Dict, Any, List

import httpx

from app.logger import logger
from app.mcp.server_manager import MCPServerManager, MCPServerConfigModel, MCPToolboxConfigModel
from app.mcp.skill_registry import SkillRegistry
from app.infrastructure.postgres import PostgresClient
from app.repository.models import MCPToolRegistration, MCPServerConfig
from app.utils.snowflake import generate_string_id


class DiscoverySyncEngine:
    """
    外部 MCP 两级发现与同步引擎。
    
    做什么：实现 Toolbox -> Server -> Tool 的级联拉取与持久化。
    为什么这样做：外部工具是通过注册在 Toolbox 上的多个 Server 提供的。系统需要通过
                HTTP 请求从 Toolbox 发现可用的 Server 列表，然后再通过 JSON-RPC
                向每个 Server 发起 tools/list 请求，获取可用工具并更新数据库。
    """
    _instance = None

    def __init__(self):
        self._manager = MCPServerManager.get_instance()
        self._skill_registry = SkillRegistry()

    @classmethod
    def get_instance(cls) -> "DiscoverySyncEngine":
        if cls._instance is None:
            cls._instance = DiscoverySyncEngine()
        return cls._instance

    async def sync_everything(self):
        """执行全量级联发现，供启动和定时任务调用"""
        logger.info("开始执行 MCP 全量发现 (Toolbox -> Servers -> Tools)")
        toolboxes = self._manager.get_all_toolboxes()
        
        for toolbox in toolboxes:
            try:
                # 级别一：发现 Server，并落盘到 mcp_server_configs 表
                servers = await self._fetch_servers_from_toolbox(toolbox)
                await self._upsert_servers_to_pg(toolbox, servers)
                
                # 级别二：发现 Tool，并落盘到 mcp_tool_registrations 表
                for server in servers:
                    await self.sync_server_tools(server)
            except Exception as e:
                logger.error(f"同步 Toolbox {toolbox.id} 异常: {e}", exc_info=True)
                
        # 刷新本地缓存供 Agent 路由使用
        pg_client = PostgresClient.get_instance()
        async with pg_client.session() as session:
            try:
                await self._skill_registry.load_from_pg(session)
            except Exception as e:
                logger.warning(f"全量同步后刷新 SkillRegistry 缓存失败: {e}", exc_info=True)

    async def _fetch_servers_from_toolbox(self, toolbox: MCPToolboxConfigModel) -> List[MCPServerConfigModel]:
        """级别一发现：调用 Toolbox API 获取 Server 列表"""
        headers = {}
        token = self._manager.resolve_toolbox_auth_token(toolbox.id)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        logger.info(f"正在从 Toolbox {toolbox.id} ({toolbox.endpoint_url}) 获取 Server 列表...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(toolbox.endpoint_url, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                servers = []
                # 假设 Toolbox 返回 { "servers": [ { "id": "srv_1", "endpoint": "https://..." } ] }
                # 这里根据实际的 Smithery / 其他 Toolbox 的数据结构来解析
                logger.info(f"从 Toolbox {toolbox.id} 获取到 {data.get('servers', [])}")
                for s_data in data.get("servers", []):
                    server = MCPServerConfigModel(
                        server_id=s_data.get("id"),
                        name=s_data.get("name", s_data.get("id")),
                        endpoint_url=s_data.get("endpoint", s_data.get("url", "")),
                        transport_type=s_data.get("transport", "http"),
                        toolbox_id=toolbox.id,
                        # 继承 toolbox 的部分配置
                        namespace=toolbox.namespace,
                        defer_loading=toolbox.defer_loading,
                        sync_interval_seconds=toolbox.sync_interval_seconds,
                        timeout_seconds=toolbox.timeout_seconds,
                        circuit_breaker=toolbox.circuit_breaker,
                        allow_tools=toolbox.allow_tools,
                        deny_tools=toolbox.deny_tools
                    )
                    servers.append(server)
                logger.info(f"从 Toolbox {toolbox.id} 发现了 {len(servers)} 个 Server。")
                return servers
            except Exception as e:
                logger.error(f"从 Toolbox {toolbox.id} 获取 Server 失败: {e}", exc_info=True)
                return []

    async def _upsert_servers_to_pg(self, toolbox: MCPToolboxConfigModel, servers: List[MCPServerConfigModel]):
        """将发现的 Server 列表 UPSERT 到 PostgreSQL"""
        if not servers:
            return

        pg_client = PostgresClient.get_instance()
        async with pg_client.session() as session:
            from sqlalchemy import select
            
            # 首先将这个 toolbox 下现有的 server 状态都置为 OFFLINE
            # (暂时用这种方式标记未在最新拉取中出现的 Server，如果需要可以先查询再 update)
            
            for server_data in servers:
                stmt = select(MCPServerConfig).where(MCPServerConfig.server_id == server_data.server_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                sync_strategies = {
                    "defer_loading": server_data.defer_loading,
                    "sync_interval_seconds": server_data.sync_interval_seconds,
                    "timeout_seconds": server_data.timeout_seconds,
                    "allow_tools": server_data.allow_tools,
                    "deny_tools": server_data.deny_tools,
                    "namespace": server_data.namespace,
                    "circuit_breaker": server_data.circuit_breaker.dict()
                }

                if existing:
                    existing.name = server_data.name
                    existing.endpoint_url = server_data.endpoint_url
                    existing.transport_type = server_data.transport_type
                    existing.toolbox_id = toolbox.id
                    existing.sync_strategies = sync_strategies
                    existing.status = "ACTIVE"
                else:
                    new_config = MCPServerConfig(
                        id=generate_string_id(),
                        server_id=server_data.server_id,
                        name=server_data.name,
                        endpoint_url=server_data.endpoint_url,
                        transport_type=server_data.transport_type,
                        toolbox_id=toolbox.id,
                        sync_strategies=sync_strategies,
                        status="ACTIVE"
                    )
                    session.add(new_config)
            await session.commit()
            
        # 同步更新 Manager 内存中的配置
        await self._manager._load_from_pg()

    async def _fetch_tools_from_server(self, server: MCPServerConfigModel) -> List[Dict[str, Any]]:
        """级别二发现：向外部 Server 发起 tools/list 请求获取工具列表。"""
        headers = {"Content-Type": "application/json"}
        # 复用所属 toolbox 的 token
        token = self._manager.resolve_auth_token(server.server_id)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": generate_string_id()
        }

        try:
            async with httpx.AsyncClient(timeout=server.timeout_seconds) as client:
                response = await client.post(server.endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if "error" in data:
                    logger.error(f"Failed to fetch tools from server {server.server_id}: {data['error']}")
                    return []
                    
                result = data.get("result", {})
                return result.get("tools", [])
        except Exception as e:
            logger.error(f"Error fetching tools from server {server.server_id}: {e}")
            return []

    def _map_risk_level(self, tool_def: Dict[str, Any]) -> str:
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

    async def sync_server_tools(self, server: MCPServerConfigModel):
        """同步指定 Server 的工具。"""
        logger.info(f"Syncing tools for server: {server.server_id} at {server.endpoint_url}")
        if not server.endpoint_url:
            return
            
        tools = await self._fetch_tools_from_server(server)
        if not tools:
            logger.warning(f"No tools found or error occurred for server {server.server_id}.")
            return

        tool_names_synced = []
        pg_client = PostgresClient.get_instance()
        async with pg_client.session() as session:
            from sqlalchemy import select
            
            for tool_def in tools:
                raw_name = tool_def.get("name")
                if not raw_name:
                    continue
                    
                tool_name = f"{server.namespace}.{raw_name}"
                
                # 黑白名单过滤
                if raw_name in server.deny_tools:
                    continue
                if "*" not in server.allow_tools and raw_name not in server.allow_tools:
                    continue

                description = tool_def.get("description", "")
                input_schema = tool_def.get("inputSchema", {})
                risk_level = self._map_risk_level(tool_def)
                
                stmt = select(MCPToolRegistration).where(MCPToolRegistration.name == tool_name)
                result = await session.execute(stmt)
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
                    session.add(new_tool)
                    
                tool_names_synced.append(tool_name)
                
            await session.commit()
            
        logger.info(f"Synced {len(tool_names_synced)} tools from {server.server_id}.")

    async def start_background_sync(self, interval_seconds: int = 3600):
        """
        启动后台定时同步任务。
        """
        logger.info(f"Starting background discovery sync with interval {interval_seconds}s")
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.sync_everything()
            except Exception as e:
                logger.error(f"Error in background sync loop: {e}", exc_info=True)