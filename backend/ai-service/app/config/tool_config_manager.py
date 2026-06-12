"""
MCP 工具配置管理器。

做什么：管理 MCP 工具的自定义配置，提供内存缓存和 PG 持久化双重能力。
        工具在运行时通过此管理器读取配置，而非直接读取 .env 环境变量。
        配置从前端 Skill 面板中每个工具条目旁的"配置"按钮设置。
为什么这样做：将工具配置与系统环境变量解耦，让用户可在前端独立配置
             每个工具的专有参数。PG 作为配置的 SSOT，内存缓存提供零延迟读取。
边界条件：
    - 启动时从 PG 加载所有 ACTIVE 状态配置到内存。
    - 配置变更后调用 reload() 刷新内存缓存。
    - 工具找不到配置时返回空字典，由工具自身使用默认值。
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from app.logger import logger


class ToolConfigManager:
    """
    MCP 工具配置管理器（单例）。

    做什么：维护 tool_name → config_data 的内存映射，
            提供配置读取和缓存刷新功能。
    """

    _instance: ToolConfigManager | None = None
    _configs: dict[str, dict[str, Any]] = {}
    _lock: Lock = Lock()

    def __new__(cls) -> ToolConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._configs = {}
            cls._lock = Lock()
        return cls._instance

    # ---- 缓存管理 ----

    def load_from_pg(self, configs: list[dict[str, Any]]) -> None:
        """
        从 PG 加载配置到内存缓存。

        做什么：接收 ToolConfigPGRepo.load_all() 返回的配置列表，
                构建 tool_name → config_data 的内存映射。
        为什么这样做：启动时调用，将 PG 数据缓存到内存，避免运行时频繁查表。
        参数:
            configs: 从 PG 加载的配置列表。
                    每项应包含 tool_name 和 config_data 字段。
        """
        with self._lock:
            self._configs.clear()
            for cfg in configs:
                tool_name = cfg.get("tool_name", "")
                config_data = cfg.get("config_data", {})
                if tool_name:
                    self._configs[tool_name] = config_data
            logger.info(f"工具配置内存缓存加载完成 count={len(self._configs)}")

    def reload_single(self, tool_name: str, config_data: dict[str, Any]) -> None:
        """
        刷新单个工具配置的内存缓存。

        做什么：更新或新增单个工具的配置缓存。
        为什么这样做：用户在前端修改配置后，调用此方法使配置即时生效。
        参数:
            tool_name: 工具名称。
            config_data: 配置键值对。
        """
        with self._lock:
            self._configs[tool_name] = config_data
            logger.info(f"工具配置缓存已刷新 tool_name={tool_name}")

    def remove(self, tool_name: str) -> None:
        """
        从缓存中移除指定工具配置。

        做什么：删除指定工具的内存缓存条目。
        为什么这样做：当用户删除（软删除）配置时，同步清理缓存。
        参数:
            tool_name: 工具名称。
        """
        with self._lock:
            self._configs.pop(tool_name, None)
            logger.info(f"工具配置缓存已移除 tool_name={tool_name}")

    # ---- 配置读取 ----

    def get_config(self, tool_name: str) -> dict[str, Any]:
        """
        获取指定工具的配置。

        做什么：从内存缓存中读取配置。如果找不到配置，返回空字典。
        为什么这样做：工具运行时调用此方法获取配置参数。
                    工具自身需要有合理的默认值兜底。
        参数:
            tool_name: 工具名称，如 "web_search"。
        返回:
            dict: 配置键值对。不存在时返回空字典。
        """
        with self._lock:
            return self._configs.get(tool_name, {})

    def get_config_value(self, tool_name: str, key: str, default: Any = None) -> Any:
        """
        获取指定工具的某个配置项。

        做什么：从配置字典中读取指定键的值，不存在时返回默认值。
        参数:
            tool_name: 工具名称。
            key: 配置键名。
            default: 默认值。
        返回:
            Any: 配置值或默认值。
        """
        config = self.get_config(tool_name)
        return config.get(key, default)

    def has_config(self, tool_name: str) -> bool:
        """
        判断指定工具是否有配置。

        参数:
            tool_name: 工具名称。
        返回:
            bool: 有配置返回 True。
        """
        with self._lock:
            return tool_name in self._configs
