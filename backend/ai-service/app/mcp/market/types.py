"""
MCP 市场数据类型定义。
"""

from typing import Any
from pydantic import BaseModel, Field


class RawDiscoveryItem(BaseModel):
    """原始采集数据条目。"""
    source: str
    source_id: str
    name: str
    description: str
    author: str = ""
    repository_url: str = ""
    homepage_url: str = ""
    endpoint_url: str = ""
    license: str = ""
    tags: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class NormalizedItem(BaseModel):
    """标准化数据条目。"""
    name: str
    display_name: str
    description: str
    author: str
    repository_url: str
    homepage_url: str
    endpoint_url: str
    license: str
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)
    logo_url: str = ""
    source: str
    original_data: dict[str, Any] = Field(default_factory=dict)
