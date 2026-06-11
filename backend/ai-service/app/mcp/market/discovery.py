"""
MCP 市场数据采集引擎。

做什么：从多个来源发现远程 MCP Server，包括官方 Registry、聚合站、
        GitHub、社区目录和开发者提交。采集的数据送入标准化层处理。
为什么这样做：远程 MCP 生态分散在多个平台，需要统一采集入口。
边界条件：
    - 同一 Server 在不同来源出现时由标准化层去重。
    - 采集失败（如来源不可达）记录日志不阻塞整体流程。
"""

import json
import httpx
import traceback
from typing import Any
from app.logger import logger
from app.mcp.market.types import RawDiscoveryItem
from app.mcp.market.collectors.base import BaseCollector


class OfficialRegistryCollector(BaseCollector):
    """官方 MCP Registry 采集器。

    做什么：从已知的官方/社区 MCP Registry 列表通过 HTTP 请求采集。
    目前支持的来源：modelcontextprotocol.io 等已知端点。
    为什么这样做：作为采集引擎的默认实现，为后续扩展 GitHub/Glama 等
                 采集器提供基线逻辑。
    """

    # 已知的公开 MCP Registry 端点
    REGISTRY_ENDPOINTS = [
        "https://registry.modelcontextprotocol.io/v0.1/servers"
    ]

    @property
    def source_name(self) -> str:
        return "official_registry"

    async def collect(self) -> list[RawDiscoveryItem]:
        """执行单次采集：从所有已知的 Registry Endpoint 获取数据。

        返回：
            list[RawDiscoveryItem]: 本次采集到的原始 MCP Server 条目列表
        """
        items: list[RawDiscoveryItem] = []

        for endpoint in self.REGISTRY_ENDPOINTS:
            # response_text 初始化为空字符串，供后续异常捕获分支使用
            response_text = ""
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        endpoint,
                        headers={"Accept": "application/json", "User-Agent": "LunaAI/1.0"},
                    )
                    response.raise_for_status()

                    # 保存原始响应文本，用于日志排查
                    response_text = response.text
                    logger.debug(f"从 {endpoint} 收到原始响应（前200字符）: {response_text[:200]}")

                    data = response.json()
                    # 尝试解析 Registry 返回的列表数据（字段名兼容不同格式）
                    server_list = data if isinstance(data, list) else data.get("servers", data.get("data", []))

                    for entry in server_list:
                        if not isinstance(entry, dict):
                            continue
                        item = RawDiscoveryItem(
                            source=self.source_name,
                            source_id=str(entry.get("id", "")),
                            name=entry.get("name", entry.get("display_name", "")),
                            description=entry.get("description", ""),
                            author=entry.get("author", entry.get("publisher", "")),
                            repository_url=entry.get("repository_url", entry.get("git_url", "")),
                            homepage_url=entry.get("homepage_url", entry.get("homepage", "")),
                            endpoint_url=entry.get("endpoint_url", entry.get("endpoint", "")),
                            license=entry.get("license", ""),
                            tags=entry.get("tags", entry.get("keywords", [])),
                            raw_data=entry,
                        )
                        if item.name:  # 只接收有名称的条目
                            items.append(item)

                logger.info(f"从 {endpoint} 采集完成，获取 {len(items)} 条 MCP Server 数据")

            except httpx.HTTPStatusError as e:
                # 详细记录 HTTP 错误状态码和响应体内容
                logger.warning(
                    f"从 {endpoint} 采集失败，HTTP 状态码异常: {e.response.status_code}，"
                    f"响应内容（前500字符）: {e.response.text[:500]}"
                )
            except httpx.RequestError as e:
                # 详细记录网络级异常：DNS 解析失败、连接超时、连接被拒等
                logger.warning(
                    f"从 {endpoint} 采集失败，请求异常（可能网络不通或被墙）: "
                    f"异常类型={type(e).__name__}，异常详情={e!s}"
                )
            except json.JSONDecodeError as e:
                # 专门捕获 JSON 解析失败，说明端点返回的不是合法 JSON（例如返回了 HTML）
                response_preview = response_text[:500] if response_text else "（未获取到 response_text，可能在 raise_for_status 之前就失败了）"
                logger.warning(
                    f"从 {endpoint} 采集失败，JSON 解析异常: {e!s}\n"
                    f"原始响应内容（前500字符）: {response_preview}"
                )
            except Exception as e:
                # 兜底异常处理：打印完整堆栈 + 异常类型，避免遗漏任何非预期错误
                logger.warning(
                    f"从 {endpoint} 采集失败，非预期异常: {type(e).__name__} - {e!s}\n"
                    f"完整堆栈:\n{traceback.format_exc()}"
                )

        return items


class DiscoveryEngine:
    """MCP 市场数据采集引擎。"""

    def __init__(self) -> None:
        self.collectors: list[BaseCollector] = [
            OfficialRegistryCollector(),
        ]

    async def run_discovery(self) -> list[RawDiscoveryItem]:
        """运行所有采集器，汇总原始数据

        返回：
            list[RawDiscoveryItem]: 所有采集器获取的原始 MCP Server 条目列表
        """
        all_items = []
        for collector in self.collectors:
            try:
                items = await collector.collect()
                all_items.extend(items)
                logger.info(f"采集器 {collector.source_name} 完成，获取 {len(items)} 条数据")
            except Exception as e:
                # 打印完整堆栈，方便定位采集器本身的代码 Bug
                logger.error(
                    f"采集器 {collector.source_name} 执行失败: {type(e).__name__} - {e!s}\n"
                    f"完整堆栈:\n{traceback.format_exc()}"
                )

        return all_items
