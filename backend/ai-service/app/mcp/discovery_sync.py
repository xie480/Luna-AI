import asyncio
from typing import Dict, Any, List

import httpx

from app.logger import get_logger
from app.mcp.server_manager import MCPServerManager, MCPServerConfigModel
from app.mcp.skill_registry import SkillRegistry
from app.repository.postgres import get_db_session
from app.repository.models import MCPToolRegistration
from app.utils.snowflake import generate_string_id

logger = get_logger("mcp.discovery_sync")


class DiscoverySyncEngine:
    """
    外部 MCP Server 工具发现与同步引擎。
    
    做什么：实现对远端 Tool 注册列表的动态发现、缓存更新和过期管理。
    为什么这样做：外部工具是动态变化的。系统需要定时或在初始化时，通过 JSON-RPC
                向远端发起 tools/list 请求，获取可用工具并更新本地缓存及数据库。
    边界条件：
        - 从 Server Manager 获取 active 的 servers。
        - 仅当工具为外部工具时，设置 is_external=True 及关联 server_id。
        - 根据 destructiveHint 动态映射风险等级。
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

    async def _fetch_tools_from_server(self, server: MCPServerConfigModel) -> List[Dict[str, Any]]:
        """向外部 Server 发起 tools/list 请求获取工具列表。"""
        headers = {"Content-Type": "application/json"}
        token = self._manager.resolve_auth_token(server.server_id)
        
        if token:
            if server.auth.type == "bearer" or server.auth.type == "service_token":
                headers["Authorization"] = f"Bearer {token}"
            elif server.auth.type == "api_key":
                # Fallback API key env parsing logic can go here. Assuming typical bearer/service token pattern
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
                    logger.error(f"Failed to fetch tools from {server.server_id}: {data['error']}")
                    return []
                    
                result = data.get("result", {})
                return result.get("tools", [])
        except Exception as e:
            logger.error(f"Error fetching tools from {server.server_id}: {e}", exc_info=True)
            return []

    def _map_risk_level(self, tool_def: Dict[str, Any]) -> str:
        """动态映射风险等级。"""
        # 默认级别
        risk_level = "L1"
        
        # MCP 协议标准注解判断
        annotations = tool_def.get("annotations", {})
        # 一些变体可能直接在顶层
        read_only_hint = tool_def.get("readOnlyHint") or annotations.get("readOnlyHint", False)
        destructive_hint = tool_def.get("destructiveHint") or annotations.get("destructiveHint", False)
        
        if destructive_hint:
            risk_level = "L2"
        elif read_only_hint:
            risk_level = "L0"
            
        return risk_level

    async def sync_all_servers(self):
        """同步所有已激活 Server 的工具。"""
        active_servers = self._manager.get_all_active_servers()
        logger.info(f"Starting discovery sync for {len(active_servers)} active servers.")
        
        for server in active_servers:
            await self.sync_server(server)

    async def sync_server(self, server: MCPServerConfigModel):
        """同步指定 Server 的工具。"""
        logger.info(f"Syncing tools for server: {server.server_id}")
        tools = await self._fetch_tools_from_server(server)
        
        if not tools:
            logger.warning(f"No tools found or error occurred for server {server.server_id}.")
            return

        tool_names_synced = []
        
        async for session in get_db_session():
            from sqlalchemy import select, update, delete
            
            for tool_def in tools:
                # 外部工具统一加前缀，避免与本地冲突
                raw_name = tool_def.get("name")
                if not raw_name:
                    continue
                    
                tool_name = f"{server.namespace}.{raw_name}"
                description = tool_def.get("description", "")
                input_schema = tool_def.get("inputSchema", {})
                risk_level = self._map_risk_level(tool_def)
                
                # Check DB Upsert
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
        # 同步后更新内存中的 SkillRegistry （假设上层会处理或触发重新加载）
        # self._skill_registry.reload_from_db()  # 根据现有的 registry 方法调用

    async def start_background_sync(self):
        """启动后台定时同步任务。"""
        # 注意：这里的实现应该交给更上层的 scheduler/worker 去管理生命周期。
        # 这是一个示例逻辑。
        pass