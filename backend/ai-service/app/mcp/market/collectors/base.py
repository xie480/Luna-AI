"""
MCP 市场数据采集器基类。
"""

from abc import ABC, abstractmethod
from typing import Any
from app.mcp.market.types import RawDiscoveryItem


class BaseCollector(ABC):
    """MCP 市场数据采集器基类。"""
    
    @abstractmethod
    async def collect(self) -> list[RawDiscoveryItem]:
        """
        执行单次采集，返回原始数据条目列表。
        """
        pass

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        采集来源名称，用于日志和审计。
        """
        pass
