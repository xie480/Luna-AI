"""
MCP 市场数据采集引擎。

做什么：从多个来源发现远程 MCP Server，包括官方 Registry、聚合站、
        GitHub、社区目录和开发者提交。采集的数据送入标准化层处理。
为什么这样做：远程 MCP 生态分散在多个平台，需要统一采集入口。
边界条件：
    - 同一 Server 在不同来源出现时由标准化层去重。
    - 采集失败（如来源不可达）记录日志不阻塞整体流程。
"""

import httpx
from typing import Any
from app.logger import logger
from app.mcp.market.types import RawDiscoveryItem
from app.mcp.market.collectors.base import BaseCollector


class OfficialRegistryCollector(BaseCollector):
    """官方 MCP Registry 采集器"""
    
    @property
    def source_name(self) -> str:
        return "official_registry"
        
    async def collect(self) -> list[RawDiscoveryItem]:
        # TODO: 接入真实的官方 Registry API
        # 这里仅作占位实现
        return []


class DiscoveryEngine:
    """MCP 市场数据采集引擎。"""
    
    def __init__(self) -> None:
        self.collectors: list[BaseCollector] = [
            OfficialRegistryCollector(),
        ]
        
    async def run_discovery(self) -> list[RawDiscoveryItem]:
        """运行所有采集器，汇总原始数据"""
        all_items = []
        for collector in self.collectors:
            try:
                items = await collector.collect()
                all_items.extend(items)
                logger.info(f"采集器 {collector.source_name} 完成，获取 {len(items)} 条数据")
            except Exception as e:
                logger.error(f"采集器 {collector.source_name} 执行失败: {e}")
                
        return all_items
