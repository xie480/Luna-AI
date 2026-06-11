"""
MCP 市场数据采集引擎。

做什么：从多个来源发现远程 MCP Server，包括官方 Registry、聚合站、
        GitHub、社区目录和开发者提交。采集的数据送入标准化层处理。
为什么这样做：远程 MCP 生态分散在多个平台，需要统一采集入口。
边界条件：
    - 同一 Server 在不同来源出现时由标准化层去重。
    - 采集失败（如来源不可达）记录日志不阻塞整体流程。
"""

import asyncio
import json
import httpx
import traceback
from typing import Any
from urllib.parse import quote
from app.logger import logger
from app.mcp.market.types import RawDiscoveryItem
from app.mcp.market.collectors.base import BaseCollector


class OfficialRegistryCollector(BaseCollector):
    """官方 MCP Registry 采集器。

    做什么：从已知的官方/社区 MCP Registry 列表通过 HTTP 请求采集。
    目前支持的来源：registry.modelcontextprotocol.io 官方 Registry。
    为什么这样做：作为采集引擎的默认实现，为后续扩展 GitHub/Glama 等
                  采集器提供基线逻辑。

    采集策略（两阶段）：
    阶段一：调用 /v0.1/servers?version=latest 获取服务器列表（含基础元数据）。
    阶段二：对每个有名称的服务器，并发调用 /v0.1/servers/{name}/versions/latest
            获取详细元数据（title、完整 packages/remotes 等）。
            使用信号量控制并发度，避免 Registry 限流。

    注意：官方 Registry 的 JSON 结构为嵌套格式，每个条目包含：
          {
            "server": { "name": "...", "title": "...", "remotes": [...], ... },
            "_meta": { ... }
          }
          解析时必须解开 server 层的嵌套。
    """

    # 已知的公开 MCP Registry 端点
    REGISTRY_ENDPOINTS = [
        "https://registry.modelcontextprotocol.io/v0.1/servers"
    ]

    # 阶段二并发获取详情时的最大并发数，控制对 Registry 的压力
    _MAX_CONCURRENT_DETAIL = 10

    @property
    def source_name(self) -> str:
        return "official_registry"

    async def collect(self) -> list[RawDiscoveryItem]:
        """执行单次采集：两阶段获取完整服务器元数据。

        阶段一：从所有已知的 Registry Endpoint 获取服务器列表（含 description、
                version、repository、packages、remotes 等基础字段）。
        阶段二：对每个服务器获取版本详情，补充 title、完整 packages/remotes
                等数据。详情数据优先于列表数据。

        返回：
            list[RawDiscoveryItem]: 本次采集到的原始 MCP Server 条目列表
        """
        items: list[RawDiscoveryItem] = []

        for endpoint in self.REGISTRY_ENDPOINTS:
            # response_text 初始化为空字符串，供后续异常捕获分支使用
            response_text = ""
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    # ===== 阶段一：获取服务器列表 =====
                    # 请求参数：只获取最新版本、限制每页数量
                    list_url = f"{endpoint}?version=latest&limit=50"
                    response = await client.get(
                        list_url,
                        headers={"Accept": "application/json", "User-Agent": "LunaAI/1.0"},
                    )
                    response.raise_for_status()
                    response_text = response.text
                    logger.info(
                        f"=== 阶段一：从 {list_url} 收到原始响应 "
                        f"（前500字符）===\n{response_text[:500]}"
                    )

                    data = response.json()

                    # 官方 Registry 返回的是 {"servers": [...], "metadata": {...}} 格式
                    # 也兼容直接返回数组的情况，或者 data 字段
                    server_list = data if isinstance(data, list) else data.get("servers", data.get("data", []))

                    # 将列表数据构建为 {name: list_data} 映射
                    list_data_map: dict[str, dict[str, Any]] = {}
                    for entry in server_list:
                        if not isinstance(entry, dict):
                            continue
                        # 官方 Registry 的每个条目是 { "server": { ... }, "_meta": { ... } } 结构
                        svr = entry.get("server", entry)
                        name = svr.get("name", svr.get("title", ""))
                        if not name:
                            continue
                        list_data_map[name] = {
                            "server": svr,
                            "_meta": entry.get("_meta", {}),
                        }

                    if not list_data_map:
                        logger.warning(
                            f"从 {endpoint} 获取的服务器列表为空，跳过详情采集。"
                            f"原始响应前500字符: {response_text[:500]}"
                        )
                        continue

                    # 日志：打印前10个服务器的名称和 description 长度，确认数据完整性
                    sample_names = list(list_data_map.keys())[:10]
                    sample_descs = {}
                    for n in sample_names:
                        svr = list_data_map[n].get("server", {})
                        desc = svr.get("description", "")
                        sample_descs[n] = f"desc_len={len(desc)} first100={desc[:100]}"
                    logger.info(
                        f"阶段一完成：从 {endpoint} 获取 {len(list_data_map)} 个服务器基础信息\n"
                        f"前10个服务器样本:\n"
                        + "\n".join(f"  [{n}] {sample_descs.get(n, '')}" for n in sample_names)
                    )

                    # ===== 阶段二：并发获取每个服务器的版本详情 =====
                    # 使用信号量控制并发度，避免被 Registry 限流
                    semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_DETAIL)
                    detail_tasks = []
                    for server_name in list_data_map:
                        task = self._fetch_server_detail(client, server_name, semaphore)
                        detail_tasks.append(task)

                    # 并发执行所有详情请求，单个失败不阻塞整体
                    detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)

                    # 构建 {name: detail_data} 映射，过滤掉失败的结果
                    detail_map: dict[str, dict[str, Any]] = {}
                    for result in detail_results:
                        if isinstance(result, Exception):
                            continue
                        if result and isinstance(result, dict):
                            name = result.get("name", "")
                            if name:
                                detail_map[name] = result

                    # 合并列表数据与详情数据，组装 RawDiscoveryItem
                    for server_name, list_data in list_data_map.items():
                        detail_data = detail_map.get(server_name)
                        item = self._build_item(server_name, list_data, detail_data)
                        items.append(item)

                    # 日志：打印采样详情，展示合并后的数据质量
                    sample_details = list(detail_map.items())[:5]
                    detail_log_lines = [
                        f"阶段二完成：成功获取 {len(detail_map)}/{len(list_data_map)} 个服务器的版本详情"
                    ]
                    for s_name, s_data in sample_details:
                        s_title = s_data.get("title", s_data.get("name", ""))
                        s_desc = s_data.get("description", "")
                        s_remotes = s_data.get("remotes", [])
                        s_repo = s_data.get("repository", {})
                        s_repo_url = s_repo.get("url", "") if isinstance(s_repo, dict) else ""
                        detail_log_lines.append(
                            f"  [{s_name}] title={s_title} desc_len={len(s_desc)} "
                            f"remotes={len(s_remotes)} repo_url={s_repo_url}"
                        )
                    logger.info("\n".join(detail_log_lines))

                # 日志：日志化最终 items 的采样，确认写入数据
                if items:
                    sample_item = items[0]
                    logger.info(
                        f"从 {endpoint} 采集完成，共 {len(items)} 条。"
                        f"首条样本:\n"
                        f"  name={sample_item.name}\n"
                        f"  description_len={len(sample_item.description)}\n"
                        f"  repository_url={sample_item.repository_url}\n"
                        f"  endpoint_url={sample_item.endpoint_url}\n"
                        f"  author={sample_item.author}\n"
                        f"  license={sample_item.license}\n"
                        f"  tags={sample_item.tags}\n"
                        f"  raw_data.server keys={list(sample_item.raw_data.get('server', {}).keys())}"
                    )
                else:
                    logger.info(f"从 {endpoint} 采集完成，获取 0 条 MCP Server 数据")

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
                # 专门捕获 JSON 解析失败，说明端点返回的不是合法 JSON
                response_preview = (
                    response_text[:500] if response_text
                    else "（未获取到 response_text，可能在 raise_for_status 之前就失败了）"
                )
                logger.warning(
                    f"从 {endpoint} 采集失败，JSON 解析异常: {e!s}\n"
                    f"原始响应内容（前500字符）: {response_preview}"
                )
            except Exception as e:
                # 兜底异常处理：打印完整堆栈，避免遗漏非预期错误
                logger.warning(
                    f"从 {endpoint} 采集失败，非预期异常: {type(e).__name__} - {e!s}\n"
                    f"完整堆栈:\n{traceback.format_exc()}"
                )

        return items

    async def _fetch_server_detail(
        self,
        client: httpx.AsyncClient,
        server_name: str,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        """获取单个服务器的版本详情。

        调用 /v0.1/servers/{serverName}/versions/latest 接口。
        使用信号量控制并发度，避免对 Registry 造成过大压力。

        参数：
            client: httpx 异步客户端
            server_name: 服务器完整名称，如 "io.github.modelcontextprotocol/filesystem"
            semaphore: 并发信号量，控制同时发出的请求数量

        返回：
            dict | None: 服务器详情数据（已解包 server 层），失败时返回 None
        """
        async with semaphore:
            try:
                # 服务器名称需要 URL 编码，将 "/" 编码为 "%2F"
                # 例如 "io.github.modelcontextprotocol/filesystem" →
                # "io.github.modelcontextprotocol%2Ffilesystem"
                encoded_name = quote(server_name, safe="")
                detail_url = (
                    f"https://registry.modelcontextprotocol.io/v0.1"
                    f"/servers/{encoded_name}/versions/latest"
                )
                response = await client.get(
                    detail_url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "LunaAI/1.0",
                    },
                )
                response.raise_for_status()
                data = response.json()

                # 响应格式：{"server": {...}, "_meta": {...}}
                # 解包 server 层，同时保留 _meta
                if not isinstance(data, dict):
                    return None

                server_data = data.get("server", data)
                if not isinstance(server_data, dict):
                    return None

                # 将 _meta 合并到返回数据中，供后续 _build_item 使用
                meta = data.get("_meta", {})
                if isinstance(meta, dict):
                    server_data["_meta"] = meta

                # 标记此数据来自详情接口
                server_data["_detail_fetched"] = True

                return server_data

            except httpx.HTTPStatusError as e:
                # 404 表示该服务器没有最新版本，301 表示重定向
                # 这些情况不需要警告日志，只用 debug 级别记录
                logger.debug(
                    f"获取服务器 [{server_name}] 版本详情失败，HTTP {e.response.status_code}"
                )
                return None
            except httpx.RequestError as e:
                logger.debug(
                    f"获取服务器 [{server_name}] 版本详情失败，请求异常: {type(e).__name__}"
                )
                return None
            except json.JSONDecodeError as e:
                logger.debug(
                    f"获取服务器 [{server_name}] 版本详情失败，JSON 解析异常: {e!s}"
                )
                return None
            except Exception as e:
                logger.debug(
                    f"获取服务器 [{server_name}] 版本详情失败，非预期异常: "
                    f"{type(e).__name__} - {e!s}"
                )
                return None

    def _build_item(
        self,
        server_name: str,
        list_data: dict[str, Any],
        detail_data: dict[str, Any] | None,
    ) -> RawDiscoveryItem:
        """从合并后的列表数据和详情数据构建 RawDiscoveryItem。

        策略：详情数据优先覆盖列表数据，列表数据作为降级回退。
        详情数据（来自 /versions/latest）包含更完整的 title、packages、
        remotes 等字段，列表数据（来自 /servers）也可能包含部分字段。

        参数：
            server_name: 服务器名称
            list_data: 阶段一获取的列表数据，格式为 {"server": {...}, "_meta": {...}}
            detail_data: 阶段二获取的详情数据（已解包 server 层），可能为 None

        返回：
            RawDiscoveryItem: 组装后的原始采集条目
        """
        # 从列表数据中提取基础信息
        svr = list_data.get("server", {})
        meta = list_data.get("_meta", {})

        # 如果存在详情数据，以详情数据覆盖/补充列表数据
        # 合并策略：{**列表数据, **详情数据}，详情数据优先
        if detail_data and isinstance(detail_data, dict):
            # 先保存详情中的 _meta（如果有的话）
            detail_meta = detail_data.pop("_meta", {}) if isinstance(detail_data, dict) else {}
            # 合并 server 数据：列表数据为基础，详情数据覆盖
            merged = {**svr, **detail_data}
            svr = merged
            # 如果详情中有 _meta，覆盖列表中的 _meta
            if detail_meta and isinstance(detail_meta, dict):
                meta = detail_meta

        # 从 _meta 中提取 source_id（发布时间戳）
        source_id = self._extract_source_id(meta)

        # 提取名称和显示名称：title 只在详情接口中返回，列表接口仅包含 name
        name = svr.get("name", "")
        display_name = svr.get("title", name)

        # 提取远程端点 URL：从 remotes 数组中取第一个可用的 URL
        endpoint_url = self._extract_remote_url(svr.get("remotes", []))

        # 提取仓库 URL
        repository = svr.get("repository", {})
        repository_url = repository.get("url", "") if isinstance(repository, dict) else ""

        # 大多数服务器没有独立主页，使用仓库 URL 作为备选
        homepage_url = repository_url

        # 提取标签
        tags = self._extract_tags(svr)

        # 提取许可证
        license_info = svr.get("license", "")

        # 提取作者：从名称命名空间推导
        author = self._extract_author(svr)

        return RawDiscoveryItem(
            source=self.source_name,
            source_id=source_id,
            name=name,
            description=svr.get("description", ""),
            author=author,
            repository_url=repository_url,
            homepage_url=homepage_url,
            endpoint_url=endpoint_url,
            license=license_info,
            tags=tags,
            raw_data={
                "server": svr,
                "_meta": meta,
                "version": svr.get("version", ""),
                "display_name": display_name,
            },
        )

    def _extract_source_id(self, _meta: dict) -> str:
        """从 _meta 字段中提取 source_id。

        官方 Registry 的 _meta 格式例如：
        {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "publishedAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
                "isLatest": true
            }
        }

        使用 publishedAt 作为 source_id，因为发布时间比更新时间更稳定。
        """
        if not _meta:
            return ""
        # 遍历所有 registry 元数据键（如 "io.modelcontextprotocol.registry/official"）
        for _key, val in _meta.items():
            if isinstance(val, dict):
                return val.get("publishedAt", val.get("updatedAt", ""))
        return ""

    def _extract_remote_url(self, remotes: list) -> str:
        """从 remotes 数组中提取第一个可用的远程端点 URL。

        官方 Registry 的 remotes 格式例如：
        [
            {"type": "streamable-http", "url": "https://example.com/mcp"},
            {"type": "sse", "url": "https://example.com/sse"}
        ]

        按优先级返回：优先 streamable-http 类型，其次 sse 类型，最后第一个可用 URL。
        """
        if not remotes or not isinstance(remotes, list):
            return ""

        # 优先选择 streamable-http 类型
        for remote in remotes:
            if isinstance(remote, dict) and remote.get("type") == "streamable-http":
                url = remote.get("url", "")
                if url:
                    return url

        # 其次选择 sse 类型
        for remote in remotes:
            if isinstance(remote, dict) and remote.get("type") == "sse":
                url = remote.get("url", "")
                if url:
                    return url

        # 最后回退到第一个有 URL 的 remotes 条目
        for remote in remotes:
            if isinstance(remote, dict):
                url = remote.get("url", "")
                if url:
                    return url

        return ""

    def _extract_tags(self, svr: dict) -> list[str]:
        """从 server 对象中提取标签。

        由于官方 Registry 不直接提供 tags 字段，从名称命名空间推导标签。
        例如 "io.github.modelcontextprotocol/filesystem" → ["github", "filesystem"]
        """
        tags = []
        name = svr.get("name", "")

        # 从 name 中提取命名空间作为标签
        if "/" in name:
            namespace = name.split("/")[0]
            # 从命名空间中提取有意义的段（跳过常见前缀 io.github 等）
            # 例如 "io.github.modelcontextprotocol" → ["modelcontextprotocol"]
            parts = namespace.split(".")
            # 从后往前取有用的命名空间段
            useful_parts = [p for p in parts if p not in ("io", "com", "org", "net", "github")]
            if useful_parts:
                tags.extend(useful_parts)
            elif parts:
                # 如果没有有用段，至少保留命名空间本身
                tags.append(namespace)

            # 从名称中提取工具名作为标签
            tool_name = name.split("/")[-1]
            if tool_name:
                tags.append(tool_name)

        return tags

    def _extract_author(self, svr: dict) -> str:
        """从服务器信息中提取作者/组织名称。

        策略：从名称命名空间推导。
        例如 "io.github.user/weather" → 作者为 "user"
             "io.github.modelcontextprotocol/filesystem" → 作者为 "modelcontextprotocol"
        """
        name = svr.get("name", "")
        if "/" in name:
            namespace = name.split("/")[0]
            parts = namespace.split(".")
            # 过滤掉常见的前缀（io, com, org, net, github），取真正的组织名
            meaningful_parts = [p for p in parts if p not in ("io", "com", "org", "net", "github")]
            if meaningful_parts:
                return meaningful_parts[-1]
            # 如果没有有意义的部分，返回整个命名空间
            return namespace
        return ""


class DiscoveryEngine:
    """MCP 市场数据采集引擎。"""

    def __init__(self) -> None:
        self.collectors: list[BaseCollector] = [
            OfficialRegistryCollector(),
        ]

    async def run_discovery(self) -> list[RawDiscoveryItem]:
        """运行所有采集器，汇总原始数据。

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
