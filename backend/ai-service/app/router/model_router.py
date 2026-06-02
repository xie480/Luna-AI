"""
Luna AI 模型路由与缓存加载模块

做什么：负责根据节点类型路由到对应的模型规格，并提供带防击穿机制的内存缓存。
为什么这样做：提高模型配置的读取性能，解耦节点逻辑与底层模型配置，支持动态扩展节点和模型映射。
"""

import asyncio
import json
from enum import Enum
from typing import Any, Dict, Optional

from app.repository.config_preset_pg import ConfigPresetPGRepo
from app.utils.singleflight import SingleFlight


class NodeType(str, Enum):
    """定义交互节点类型"""
    CHAT = "chat"
    SUMMARIZE = "summarize"


class ModelSize(str, Enum):
    """定义模型规格标识"""
    BIG = "big"
    SMALL = "small"
    MEDIUM = "medium"


class ModelRouter:
    """模型路由与缓存加载模块"""

    def __init__(self, preset_repo: ConfigPresetPGRepo):
        self.preset_repo = preset_repo
        self.node_to_size_map: Dict[NodeType, ModelSize] = {
            NodeType.CHAT: ModelSize.BIG,
            NodeType.SUMMARIZE: ModelSize.SMALL,
        }
        self._cache: Dict[ModelSize, Dict[str, Any]] = {}
        self._singleflight = SingleFlight()
        self._cache_lock = asyncio.Lock()

    def register_node(self, node_type: NodeType, size: ModelSize) -> None:
        """动态注册或更新节点路由映射（提供良好的扩展性）"""
        self.node_to_size_map[node_type] = size

    async def clear_cache(self, size: Optional[ModelSize] = None) -> None:
        """清空指定规格或所有缓存（用于配置更新时）"""
        async with self._cache_lock:
            if size is not None:
                self._cache.pop(size, None)
            else:
                self._cache.clear()

    async def get_model_for_node(self, node_type: NodeType) -> Dict[str, Any]:
        """
        根据节点类型路由并获取对应的模型配置
        """
        # 1. 查询映射字典获取对应的模型标识
        size = self.node_to_size_map.get(node_type)
        if not size:
            raise ValueError(f"未知的交互节点类型: {node_type}")

        # 2. 尝试从内存缓存中获取（缓存命中）
        async with self._cache_lock:
            if size in self._cache:
                return self._cache[size]

        # 3. 缓存缺失，处理并发读取情况（防止缓存击穿）
        async def _load_and_cache():
            # 再次检查缓存（双重检查锁定 DCL）
            async with self._cache_lock:
                if size in self._cache:
                    return self._cache[size]

            # 4. 从模型库（数据库）中安全地检索出目标模型的配置
            config = await self._fetch_config_from_db(size)

            # 5. 将其加载到内存缓存中以便当前和后续操作快速调用
            async with self._cache_lock:
                self._cache[size] = config

            return config

        return await self._singleflight.do(size.value, _load_and_cache)

    async def _fetch_config_from_db(self, size: ModelSize) -> Dict[str, Any]:
        """从数据库获取当前激活的预设，并提取对应规格的配置"""
        active_preset = await self.preset_repo.get_active()
        if not active_preset:
            raise RuntimeError("当前没有激活的 API 配置预设")

        if size == ModelSize.BIG:
            config_dict = active_preset.large_model_config
        elif size == ModelSize.MEDIUM:
            config_dict = active_preset.medium_model_config
        elif size == ModelSize.SMALL:
            config_dict = active_preset.small_model_config
        else:
            raise ValueError(f"不支持的模型规格: {size}")

        # SQLAlchemy JSONB 已经是 dict，不需要 json.loads
        if isinstance(config_dict, str):
            try:
                return json.loads(config_dict)
            except Exception as e:
                raise RuntimeError(f"解析模型配置 JSON 失败: {e}")
                
        return config_dict
