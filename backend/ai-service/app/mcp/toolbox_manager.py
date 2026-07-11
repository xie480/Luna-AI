import os
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from app.logger import logger

class ToolboxAuthConfig(BaseModel):
    type: str = Field("none", description="鉴权类型: none, service_token, api_key")
    token_env: Optional[str] = Field(None, description="环境变量中的 Token 名称")

class ToolboxConfigModel(BaseModel):
    toolbox_id: str = Field(..., description="Toolbox 唯一标识，例如 smithery_main")
    name: str = Field(..., description="友好显示名称")
    endpoint_url: str = Field(..., description="路由根地址")
    transport_type: str = Field("sse", description="通信协议类型")
    auth: ToolboxAuthConfig = Field(default_factory=ToolboxAuthConfig)
    timeout_seconds: int = Field(30, description="超时时间")
    # 不再包含 allow_tools/deny_tools，这些治理应在 Skill 层或 Gating 层实现

class ToolboxConfigManager:
    """
    负责加载与管理纯网络层的 Toolbox / Gateway 连接配置。
    【重构规则】强制只读 YAML 与系统环境变量，彻底切断与 PostgreSQL 的交互。
    """
    _instance = None

    def __init__(self):
        self._toolboxes: Dict[str, ToolboxConfigModel] = {}
        # 兼容旧路径，推荐逐步迁移至 config/mcp_toolboxes.yaml
        self._config_paths = [
            Path("config/mcp_toolboxes.yaml"),
            Path("config/mcp_servers.yaml")
        ]

    @classmethod
    def get_instance(cls) -> "ToolboxConfigManager":
        if cls._instance is None:
            cls._instance = ToolboxConfigManager()
        return cls._instance

    def initialize(self):
        """同步启动时加载。不传任何 PG DB Session。"""
        logger.info("Initializing ToolboxConfigManager (In-Memory Only)...")
        self._load_from_yaml()
        logger.info(f"Loaded {len(self._toolboxes)} external toolboxes configs.")

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

    def _load_from_yaml(self):
        config_path_to_use = None
        for path in self._config_paths:
            if path.exists():
                config_path_to_use = path
                break
                
        if not config_path_to_use:
            logger.warning("No toolbox config file found.")
            return

        try:
            with open(config_path_to_use, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f)
            
            yaml_data = self._resolve_env_vars_in_dict(yaml_data)
            
            # 兼容旧配置中的 key 'mcp_servers'
            targets = yaml_data.get("mcp_toolboxes") or yaml_data.get("mcp_servers", [])
            
            for tb_data in targets:
                t_id = tb_data.get("id")
                if not t_id:
                    continue
                
                auth_data = tb_data.get("auth", {})
                
                model = ToolboxConfigModel(
                    toolbox_id=t_id,
                    name=tb_data.get("name", t_id),
                    endpoint_url=tb_data.get("endpoint_url", ""),
                    transport_type=tb_data.get("transport_type", "sse"),
                    auth=ToolboxAuthConfig(**auth_data),
                    timeout_seconds=tb_data.get("timeout_seconds", 30)
                )
                self._toolboxes[t_id] = model
                
        except Exception as e:
            logger.error(f"Failed to load toolbox configs from YAML: {e}", exc_info=True)

    def get_all_toolboxes(self) -> List[ToolboxConfigModel]:
        return list(self._toolboxes.values())
        
    def get_toolbox_config(self, toolbox_id: str) -> Optional[ToolboxConfigModel]:
        return self._toolboxes.get(toolbox_id)
        
    def resolve_auth_token(self, toolbox_id: str) -> Optional[str]:
        """
        安全解析服务器鉴权 Token。
        从环境变量中获取，禁止在内存或数据库中明文存储 Token。
        """
        config = self.get_toolbox_config(toolbox_id)
        if not config:
            return None
            
        if config.auth.type == "none":
            return None
            
        if config.auth.token_env:
            token = os.environ.get(config.auth.token_env)
            if not token:
                logger.warning(f"Auth token environment variable '{config.auth.token_env}' not set for toolbox {toolbox_id}")
            return token
            
        return None
