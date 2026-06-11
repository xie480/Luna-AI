"""
MCP 市场标准化引擎。

做什么：对从不同来源采集的 MCP Server 元数据进行去重和字段映射标准化。
        同一 Server 在不同来源可能以不同名称/描述出现，通过名称模糊匹配
        和仓库 URL 精确匹配来识别同一实体。
为什么这样做：避免同一个 MCP Server 在市场中重复出现，确保用户体验。
"""

import re
from typing import Any
from app.logger import logger
from app.mcp.market.types import RawDiscoveryItem, NormalizedItem


class MarketNormalizer:
    """MCP 市场数据标准化引擎。"""

    async def normalize(self, items: list[RawDiscoveryItem]) -> list[NormalizedItem]:
        """
        标准化数据条目。
        
        做什么：对同一 Server 出现在多个来源的情况进行去重，
                合并元数据，统一字段映射。
        返回：去重并标准化后的条目列表。
        """
        normalized_items: list[NormalizedItem] = []
        for item in items:
            normalized_items.append(self._map_to_normalized(item))
            
        return await self.deduplicate(normalized_items)

    def _map_to_normalized(self, item: RawDiscoveryItem) -> NormalizedItem:
        """映射原始数据到标准化结构"""
        # 简单归一化名称：转小写，去除非字母数字
        clean_name = re.sub(r'[^a-z0-9]', '', item.name.lower())
        if not clean_name:
            clean_name = item.name.lower().replace(' ', '-')
            
        # 提取分类标签
        category = "uncategorized"
        tags = set(item.tags)
        
        # 基于内容进行简单的分类推断
        lower_desc = item.description.lower()
        if "github" in lower_desc or "git" in lower_desc or "code" in lower_desc:
            category = "developer_tools"
        elif "database" in lower_desc or "sql" in lower_desc or "postgres" in lower_desc:
            category = "data_access"
        elif "system" in lower_desc or "file" in lower_desc or "os" in lower_desc:
            category = "system"
            
        return NormalizedItem(
            name=clean_name,
            display_name=item.name,
            description=item.description,
            author=item.author,
            repository_url=item.repository_url,
            homepage_url=item.homepage_url,
            endpoint_url=item.endpoint_url,
            license=item.license,
            category=category,
            tags=list(tags),
            source=item.source,
            original_data=item.raw_data
        )

    async def deduplicate(self, items: list[NormalizedItem]) -> list[NormalizedItem]:
        """
        去重引擎。
        
        策略（按优先级）：
        1. repository_url 精确匹配 → 保留数据最完整的一条
        2. name 归一化 + author 精确匹配 → 合并 tags 和描述
        3. endpoint_url 精确匹配 → 保留新增度更高的一条
        """
        if not items:
            return []
            
        repo_map: dict[str, NormalizedItem] = {}
        name_author_map: dict[str, NormalizedItem] = {}
        endpoint_map: dict[str, NormalizedItem] = {}
        
        final_list: list[NormalizedItem] = []
        
        for item in items:
            is_dup = False
            
            # 策略 1: Repo URL 匹配
            if item.repository_url:
                if item.repository_url in repo_map:
                    is_dup = True
                    # 如果当前 item 的数据更丰富，更新现有的
                    existing = repo_map[item.repository_url]
                    self._merge_items(existing, item)
                else:
                    repo_map[item.repository_url] = item
                    
            # 策略 2: Name + Author 匹配
            if not is_dup and item.name and item.author:
                key = f"{item.name}::{item.author}"
                if key in name_author_map:
                    is_dup = True
                    existing = name_author_map[key]
                    self._merge_items(existing, item)
                else:
                    name_author_map[key] = item
                    
            # 策略 3: Endpoint URL 匹配
            if not is_dup and item.endpoint_url:
                if item.endpoint_url in endpoint_map:
                    is_dup = True
                    existing = endpoint_map[item.endpoint_url]
                    self._merge_items(existing, item)
                else:
                    endpoint_map[item.endpoint_url] = item
                    
            if not is_dup:
                final_list.append(item)
                
        return final_list

    def _merge_items(self, target: NormalizedItem, source: NormalizedItem) -> None:
        """合并条目数据，保留较完整的信息"""
        # 合并 tags
        merged_tags = set(target.tags) | set(source.tags)
        target.tags = list(merged_tags)
        
        # 补全缺失字段
        if not target.description and source.description:
            target.description = source.description
        if not target.endpoint_url and source.endpoint_url:
            target.endpoint_url = source.endpoint_url
        if target.category == "uncategorized" and source.category != "uncategorized":
            target.category = source.category
