import os
import yaml
from pathlib import Path
from typing import Dict, Optional, List, Any
from pydantic import BaseModel, Field

from app.logger import logger
from app.infrastructure.postgres import PostgresClient
from app.repository.models import MCPServerConfig
from app.utils.snowflake import generate_string_id
from app.config.settings import settings

class CircuitBreakerConfig(BaseModel):
    failure_threshold: float = Field(0.5, description="熔断阈值")
    recovery_timeout: int = Field(60, description="恢复超时时间（秒）")
    min_request_count: int = Field(5, description="最小请求次数")

class AuthConfig(BaseModel):
    type: str = Field("none", description="鉴权类型: none, service_token, api_key")
    token_env: Optional[str] = Field(None, description="环境变量中的 Token 名称")

class MCPToolboxConfigModel(BaseModel):
    id: str = Field(..., description="Toolbox唯一逻辑标识")
    name: str = Field(..., description="Toolbox友好名称")
    endpoint_url: str = Field(..., description="Toolbox API地址")
    transport_type: str = Field("http", description="传输协议: http/sse")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    namespace: str = Field("default", description="命名空间")
    defer_loading: bool = Field(True, description="是否延迟加载")
    sync_interval_seconds: int = Field(3600, description="同步发现间隔（秒）")
    timeout_seconds: int = Field(30, description="请求超时时间（秒）")
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    allow_tools: List[str] = Field(["*"], description="允许的工具白名单")
    deny_tools: List[str] = Field([], description="拒绝的工具黑名单")

class MCPServerConfigModel(BaseModel):
    id: str = Field(default_factory=generate_string_id)
    server_id: str = Field(..., description="服务器唯一逻辑标识")
    name: str = Field(..., description="服务器友好名称")
    endpoint_url: str = Field(..., description="外部服务器地址")
    transport_type: str = Field("http", description="传输协议: http/sse")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    namespace: str = Field("default", description="命名空间")
    defer_loading: bool = Field(True, description="是否延迟加载")
    sync_interval_seconds: int = Field(3600, description="同步发现间隔（秒）")
    timeout_seconds: int = Field(30, description="请求超时时间（秒）")
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    allow_tools: List[str] = Field(["*"], description="允许的工具白名单")
    deny_tools: List[str] = Field([], description="拒绝的工具黑名单")
    status: str = Field("ACTIVE", description="当前状态: ACTIVE, OFFLINE, DISABLED")
    toolbox_id: Optional[str] = Field(None, description="所属 Toolbox ID")

class MCPServerManager:
    """
    外部 MCP Server 管理器。
    
    做什么：实现外部 MCP Server 信息的动态配置、凭证管理和可用性维护。
    为什么这样做：避免硬编码，系统将从 PostgreSQL 数据库和本地 config.yaml（或环境变量）双轨加载配置。
                敏感凭证强制从环境变量或 OS Keychain 中读取。
    边界条件：
        - 从 yaml 文件初始化配置到 PG。
        - 运行时从 PG 或内存中获取配置。
        - 提供获取认证信息的安全方法。
    """
    _instance = None

    def __init__(self):
        self._configs: Dict[str, MCPServerConfigModel] = {}
        self._toolboxes: Dict[str, MCPToolboxConfigModel] = {}
        self._config_path = Path("config/mcp_servers.yaml") # 仍然使用原文件名

    @classmethod
    def get_instance(cls) -> "MCPServerManager":
        if cls._instance is None:
            cls._instance = MCPServerManager()
        return cls._instance

    async def initialize(self, pg_client: PostgresClient):
        """
        初始化 Server Manager，加载 Toolbox 配置，然后加载 PG 中的 Server。
        """
        logger.info("Initializing MCPServerManager...")
        self._load_toolboxes_from_yaml()
        await self._load_from_pg(pg_client)
        logger.info(f"MCPServerManager initialized with {len(self._toolboxes)} toolboxes and {len(self._configs)} servers.")

    def _resolve_env_vars_in_dict(self, data: Any) -> Any:
        """递归解析字典/列表中的环境变量占位符，例如 ${MY_VAR:-default}"""
        import re
        env_pattern = re.compile(r'\$\{([^}]+)\}')
        
        def replace_match(match):
            inner = match.group(1)
            parts = inner.split(":-", 1)
            var_name = parts[0]
            default_val = parts[1] if len(parts) > 1 else ""
            val = os.environ.get(var_name, default_val)
            return val
            
        if isinstance(data, dict):
            return {k: self._resolve_env_vars_in_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._resolve_env_vars_in_dict(v) for v in data]
        elif isinstance(data, str):
            # 将类似 "true"/"false" 解析回 boolean 或者数字
            resolved = env_pattern.sub(replace_match, data)
            if resolved.lower() == "true":
                return True
            if resolved.lower() == "false":
                return False
            try:
                if "." in resolved:
                    return float(resolved)
                return int(resolved)
            except ValueError:
                return resolved
        return data

    def _load_toolboxes_from_yaml(self):
        """从 YAML 配置文件中加载 Toolbox 预设，并支持 ${ENV_VAR} 环境变量挂载。"""
        if not self._config_path.exists():
            logger.warning(f"MCP server config file {self._config_path} not found.")
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            
            yaml_data = self._resolve_env_vars_in_dict(yaml_data)
                
            if not yaml_data or "mcp_toolboxes" not in yaml_data:
                return

            for tb_data in yaml_data["mcp_toolboxes"]:
                tb_id = tb_data.get("id")
                if not tb_id:
                    continue

                cb_data = tb_data.get("circuit_breaker", {})
                cb_config = CircuitBreakerConfig(
                    failure_threshold=cb_data.get("failure_threshold", 0.5),
                    recovery_timeout=cb_data.get("recovery_timeout", 60),
                    min_request_count=cb_data.get("min_request_count", 5)
                )

                auth_data = tb_data.get("auth", {})
                auth_config = AuthConfig(
                    type=auth_data.get("type", "none"),
                    token_env=auth_data.get("token_env")
                )

                toolbox = MCPToolboxConfigModel(
                    id=tb_id,
                    name=tb_data.get("name", tb_id),
                    endpoint_url=tb_data.get("endpoint_url", ""),
                    transport_type=tb_data.get("transport_type", "http"),
                    auth=auth_config,
                    namespace=tb_data.get("namespace", "default"),
                    defer_loading=tb_data.get("defer_loading", True),
                    sync_interval_seconds=tb_data.get("sync_interval_seconds", 3600),
                    timeout_seconds=tb_data.get("timeout_seconds", 30),
                    circuit_breaker=cb_config,
                    allow_tools=tb_data.get("allow_tools", ["*"]),
                    deny_tools=tb_data.get("deny_tools", [])
                )
                self._toolboxes[tb_id] = toolbox

            logger.info(f"Loaded {len(self._toolboxes)} toolboxes from YAML.")
        except Exception as e:
            logger.error(f"Failed to load MCP toolboxes from YAML: {e}", exc_info=True)

    async def _load_from_pg(self, pg_client: PostgresClient):
        """从 PG 数据库加载配置到内存。"""
        try:
            async with pg_client.session() as session:
                from sqlalchemy import select
                stmt = select(MCPServerConfig)
                result = await session.execute(stmt)
                records = result.scalars().all()

                for record in records:
                    sync_strategies = record.sync_strategies or {}
                    cb_data = sync_strategies.get("circuit_breaker", {})
                    
                    cb_config = CircuitBreakerConfig(
                        failure_threshold=cb_data.get("failure_threshold", 0.5),
                        recovery_timeout=cb_data.get("recovery_timeout", 60),
                        min_request_count=cb_data.get("min_request_count", 5)
                    )
                    
                    auth_config = AuthConfig(
                        type=record.auth_config.get("type", "none"),
                        token_env=record.auth_config.get("token_env")
                    )

                    model = MCPServerConfigModel(
                        id=record.id,
                        server_id=record.server_id,
                        name=record.name,
                        endpoint_url=record.endpoint_url,
                        transport_type=record.transport_type,
                        auth=auth_config,
                        namespace=sync_strategies.get("namespace", "default"),
                        defer_loading=sync_strategies.get("defer_loading", True),
                        sync_interval_seconds=sync_strategies.get("sync_interval_seconds", 3600),
                        timeout_seconds=sync_strategies.get("timeout_seconds", 30),
                        circuit_breaker=cb_config,
                        allow_tools=sync_strategies.get("allow_tools", ["*"]),
                        deny_tools=sync_strategies.get("deny_tools", []),
                        status=record.status,
                        toolbox_id=record.toolbox_id
                    )
                    self._configs[record.server_id] = model
        except Exception as e:
            logger.error(f"Failed to load MCP server configs from PG: {e}", exc_info=True)

    def get_toolbox(self, toolbox_id: str) -> Optional[MCPToolboxConfigModel]:
        return self._toolboxes.get(toolbox_id)

    def get_all_toolboxes(self) -> List[MCPToolboxConfigModel]:
        return list(self._toolboxes.values())

    def get_server_config(self, server_id: str) -> Optional[MCPServerConfigModel]:
        """获取外部服务器配置。"""
        return self._configs.get(server_id)

    def get_all_active_servers(self) -> List[MCPServerConfigModel]:
        """获取所有激活的服务器。"""
        return [c for c in self._configs.values() if c.status == "ACTIVE"]

    def resolve_toolbox_auth_token(self, toolbox_id: str) -> Optional[str]:
        """
        安全解析 Toolbox 鉴权 Token。
        从环境变量中获取。
        """
        tb = self.get_toolbox(toolbox_id)
        if not tb or tb.auth.type == "none" or not tb.auth.token_env:
            return None
        token = os.environ.get(tb.auth.token_env)
        if not token:
            logger.warning(f"Auth token env '{tb.auth.token_env}' not set for toolbox {toolbox_id}")
        return token

    def resolve_auth_token(self, server_id: str) -> Optional[str]:
        """
        安全解析服务器鉴权 Token。对于 toolbox 来源的 server，可能复用 toolbox 的 token。
        从环境变量中获取，禁止在内存或数据库中明文存储 Token。
        """
        config = self.get_server_config(server_id)
        if not config:
            return None
            
        if config.auth.type == "none":
            return None
            
        if config.auth.token_env:
            token = os.environ.get(config.auth.token_env)
            if not token:
                logger.warning(f"Auth token environment variable '{config.auth.token_env}' not set for server {server_id}")
            return token
            
        return None
