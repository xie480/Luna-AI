import asyncio
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.logger import logger
from app.mcp.toolbox_manager import ToolboxConfigManager, ToolboxConfigModel
from app.mcp.connection_manager import McpConnectionManager
from app.mcp.skill_registry import SkillRegistry
from app.infrastructure.postgres import PostgresClient
from app.utils.snowflake import generate_string_id

# 需要通过延迟导入避免循环依赖
# from app.models.layer3_repository.skills import SkillModel
# from app.models.layer3_repository.tools import MCPToolRegistration


class DiscoverySyncEngine:
    """
    负责驱动服务发现循环，拉取 Toolbox 数据并重塑为系统标准 Skill 架构。
    """
    _instance = None

    def __init__(self):
        self.config_manager = ToolboxConfigManager.get_instance()
        self.connection_manager = McpConnectionManager.get_instance()
        self.skill_registry = SkillRegistry()

    @classmethod
    def get_instance(cls) -> "DiscoverySyncEngine":
        if cls._instance is None:
            cls._instance = DiscoverySyncEngine()
        return cls._instance

    async def sync_everything(self, pg_client: PostgresClient):
        """执行一次完整的发现与注册生命周期"""
        logger.info("Starting external MCP discovery sync cycle...")
        toolboxes = self.config_manager.get_all_toolboxes()
        
        for toolbox in toolboxes:
            await self._process_toolbox(pg_client, toolbox)
            
        # 所有同步结束后，通知 SkillRegistry 重新从 PG 拉取最新形态以供 DAG 引擎使用
        async with pg_client.session() as session:
            await self.skill_registry.load_from_pg(session)
            
        logger.info("Sync cycle completed. Skill registry cache refreshed.")

    async def _process_toolbox(self, pg_client: PostgresClient, toolbox: ToolboxConfigModel):
        logger.info(f"Connecting to Toolbox [{toolbox.name}] at {toolbox.endpoint_url}")
        
        try:
            import httpx
            import urllib.parse
            
            # 从 endpoint_url 提取 namespace
            path_parts = urllib.parse.urlparse(toolbox.endpoint_url).path.strip("/").split("/")
            namespace = path_parts[-1] if path_parts else ""
            
            if not namespace:
                logger.warning(f"Cannot extract namespace from endpoint_url {toolbox.endpoint_url}")
                return

            token = self.config_manager.resolve_auth_token(toolbox.toolbox_id)
            base_url = "https://api.smithery.ai"
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                # 1. 获取 Server 列表
                servers_url = f"{base_url}/connect/{namespace}"
                resp = await client.get(servers_url)
                resp.raise_for_status()
                data = resp.json()
                
                connections = data.get("connections", [])
                logger.info(f"Found {len(connections)} servers in toolbox {toolbox.toolbox_id}")
                
                for connection in connections:
                    server_id = connection["connectionId"]
                    server_name = connection.get("name") or connection.get("displayName") or server_id
                    
                    # 尝试从 connection 的 serverInfo 中获取更好的描述信息
                    server_desc = ""
                    server_info = connection.get("serverInfo", {})
                    if isinstance(server_info, dict):
                        server_desc = server_info.get("description", "")
                    
                    if not server_desc:
                        server_desc = connection.get("description") or f"External MCP Server ({server_name}) provided via {toolbox.name}"
                    
                    # 尝试从 connection 提取额外的元数据
                    tags = ["mcp", "external"]
                    # 尝试从 connection 的原始信息中提取 tag
                    if server_name:
                        tags.append(server_name.lower())
                    
                    author = "MCP Remote"
                    if isinstance(server_info, dict) and "author" in server_info:
                        author = server_info["author"]
                        
                    metadata = {"tags": tags, "author": author}

                    # 2. 为每个 Server 注册一个 Skill
                    async with pg_client.session() as db_session:
                        skill_id = await self._register_server_as_skill(db_session, toolbox, server_id, server_name, server_desc, metadata)
                        await db_session.commit()
                    
                    # 3. 获取该 Server 的 Tools
                    tools_url = f"{base_url}/connect/{namespace}/{server_id}/.tools"
                    tools_resp = await client.get(tools_url)
                    tools_resp.raise_for_status()
                    tools_data = tools_resp.json()
                    
                    raw_tools = tools_data.get("tools", []) if isinstance(tools_data, dict) else tools_data
                    
                    # 4. 注册 Tools
                    async with pg_client.session() as db_session:
                        await self._sync_tools_for_skill(db_session, skill_id, toolbox.toolbox_id, raw_tools)
                        await db_session.commit()

        except Exception as e:
            logger.error(f"Failed to process toolbox {toolbox.toolbox_id}: {e}", exc_info=True)


    async def _register_server_as_skill(self, session: AsyncSession, toolbox: ToolboxConfigModel, server_id: str, server_name: str, server_desc: str, metadata: dict) -> str:
        """
        将 Toolbox 发现的子 Server 封装为系统的 Skill。
        """
        from app.repository.models import Skill

        stmt = select(Skill).where(
            and_(
                Skill.source == "mcp_proxy",
                Skill.toolbox_id == toolbox.toolbox_id,
                Skill.proxy_meta['original_server_id'].astext == server_id
            )
        )
        result = await session.execute(stmt)
        existing_skill = result.scalar_one_or_none()
        
        if not existing_skill:
            skill_id = generate_string_id()
            new_skill = Skill(
                id=skill_id,
                name=server_name,
                description=server_desc,
                source="mcp_proxy",
                toolbox_id=toolbox.toolbox_id,
                proxy_meta={"original_server_id": server_id},
                enabled=True,
                metadata_=metadata,
            )
            session.add(new_skill)
            logger.info(f"Registered new MCP Server as Skill. Skill ID: {skill_id}, Name: {server_name}")
            return skill_id
        else:
            if existing_skill.name != server_name:
                existing_skill.name = server_name
            if existing_skill.description != server_desc:
                existing_skill.description = server_desc
            
            # 更新 metadata
            if existing_skill.metadata_ != metadata:
                existing_skill.metadata_ = metadata
                
            logger.debug(f"MCP Server -> Skill mapping already exists. Skill ID: {existing_skill.id}")
            return existing_skill.id


    async def _sync_tools_for_skill(self, session: AsyncSession, skill_id: str, toolbox_id: str, tools: list[dict]):
        """拉取 Tool 并挂载到生成的 Skill"""
        from app.repository.models import MCPToolRegistration
        from app.repository.models import Skill
        
        # 为了生成 prefix，需要获取 skill name
        stmt = select(Skill.name).where(Skill.id == skill_id)
        result = await session.execute(stmt)
        skill_name = result.scalar_one_or_none()
        
        # 移除空格并将名称规范化，用于前缀
        normalized_skill_name = skill_name.replace(" ", "_").lower() if skill_name else ""
        prefix = f"{normalized_skill_name}." if normalized_skill_name else ""
        
        tool_names_synced = []
        for raw_tool in tools:
            base_tool_name = raw_tool.get("name")
            if not base_tool_name:
                continue
                
            # MCP 外部工具注册命名规范: mcp_name.toolname
            tool_name = f"{prefix}{base_tool_name}"
                
            tool_schema = raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {}
            description = raw_tool.get("description") or ""
            
            # 解析 annotations 判断风险等级
            # 默认假设最保守的风险等级 L2 (高危)
            risk_level = "L2"
            annotations = raw_tool.get("annotations", {})
            if isinstance(annotations, dict):
                is_destructive = annotations.get("destructiveHint", True)
                is_open_world = annotations.get("openWorldHint", True)
                is_read_only = annotations.get("readOnlyHint", False)
                is_idempotent = annotations.get("idempotentHint", False)
                
                if is_destructive or is_open_world:
                    risk_level = "L2" # 高危
                elif is_read_only and is_idempotent and not is_destructive:
                    risk_level = "L0" # 低危
                else:
                    risk_level = "L1" # 中危/未知
            
            # 启发式回退：如果没有任何 annotation 或依然是 L2，并且名字看起来像只读
            if not annotations or risk_level == "L2":
                safe_prefixes = ("get_", "read_", "list_", "search_", "query_", "fetch_", "describe_")
                if base_tool_name.lower().startswith(safe_prefixes):
                    risk_level = "L0" # 启发式降级为低危
            
            stmt = select(MCPToolRegistration).where(
                MCPToolRegistration.name == tool_name
            )
            result = await session.execute(stmt)
            existing_tool = result.scalar_one_or_none()
            
            if not existing_tool:
                new_tool = MCPToolRegistration(
                    id=generate_string_id(),
                    skill_id=skill_id,
                    name=tool_name,
                    description=description,
                    parameters_schema=tool_schema,
                    risk_level=risk_level,
                    enabled=True,
                    server_id=toolbox_id, # 仍保留该字段方便执行器路由
                    is_external=True
                )
                session.add(new_tool)
                logger.info(f"Mounted Tool '{tool_name}' under Skill ID '{skill_id}' with Risk '{risk_level}'.")
            else:
                # 只有当它是外部工具或者我们确认要覆盖它时才更新
                # 这避免了将已有的本地工具覆盖为外部工具
                if existing_tool.is_external:
                    existing_tool.skill_id = skill_id
                    existing_tool.parameters_schema = tool_schema
                    existing_tool.description = description
                    existing_tool.server_id = toolbox_id
                    existing_tool.risk_level = risk_level
            
            tool_names_synced.append(tool_name)
            
        logger.info(f"Synced {len(tool_names_synced)} tools under skill {skill_id}.")

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
