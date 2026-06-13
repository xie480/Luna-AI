"""
MCP 内置工具：通过 SearXNG 执行网络搜索。

做什么：提供通过 SearXNG 搜索引擎实例执行网络搜索的工具实现。
        支持并发请求、自动翻页、自定义查询、分类筛选和语言过滤。
        作为 L0 级低危工具（仅发起只读 HTTP GET 请求），直接放行无需用户确认。
为什么这样做：Phase 12 需要接入至少一个具备实际能力的数据获取工具来验证
              工具链路在数据获取场景下的完整性。SearXNG 作为自托管的元搜索引擎，
              满足本地优先原则，无需依赖第三方搜索 API 密钥。
边界条件：
    - 依赖本地或局域网部署的 SearXNG 实例，URL 通过 ToolConfig 配置。
    - 用户在前端 Skill 面板的 web_search 工具条目中，点击"配置"按钮设置。
    - SearXNG 实例必须启用 JSON API（通过 searxng.yml 配置）。
    - 搜索失败时返回友好错误提示，不影响主流程。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config.tool_config_manager import ToolConfigManager
from app.logger import logger


# ============================================================
# 工具配置键名常量（与前端配置表单字段对应）
# ============================================================

# 工具名称，用于 ToolConfigManager 中查找配置
TOOL_NAME: str = "web_search"

# 配置键名
CONFIG_KEY_BASE_URL: str = "base_url"                               # SearXNG 实例基础 URL
CONFIG_KEY_TIMEOUT: str = "timeout"                                 # 请求超时秒数
CONFIG_KEY_CONCURRENT_REQUESTS: str = "concurrent_requests"         # 并发请求数量
CONFIG_KEY_RESULTS_PER_REQUEST: str = "results_per_request"         # 每个请求的搜索结果数量
CONFIG_KEY_MAX_URL_FETCH_LENGTH: str = "max_url_fetch_length"       # URL抓取内容长度上限
CONFIG_KEY_SAFE_SEARCH_LEVEL: str = "safe_search_level"             # 安全搜索级别


# ============================================================
# 常量定义
# ============================================================

_SEARXNG_DEFAULT_TIMEOUT: float = 15.0
_DEFAULT_CONCURRENT_REQUESTS: int = 3
_DEFAULT_RESULTS_PER_REQUEST: int = 10
_DEFAULT_MAX_URL_FETCH_LENGTH: int = 8192
_DEFAULT_SAFE_SEARCH_LEVEL: int = 1


# ============================================================
# 专属多轮记忆 Memory Schema 定义
# ============================================================

WEB_SEARCH_MEMORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "search_goal": {
            "type": "string",
            "description": "本次总的搜索目的"
        },
        "previous_query": {
            "type": "string",
            "description": "刚尝试搜索的关键词"
        },
        "previous_categories": {
            "type": "string",
            "description": "上一轮使用的分类"
        },
        "previous_language": {
            "type": "string",
            "description": "上一轮使用的语言"
        },
        "previous_time_range": {
            "type": "string",
            "description": "上一轮使用的时间范围"
        },
        "previous_results_summary": {
            "type": "string",
            "description": "上一轮搜索得到的核心结果或没找到的原因"
        },
        "attempted_queries": {
            "type": "string",
            "description": "历史已经尝试过的所有搜索词列表，格式如 ['词1', '词2']"
        },
        "gathered_information": {
            "type": "string",
            "description": "至今累积搜集到的有效关键信息"
        },
        "need_continue_search": {
            "type": "string",
            "enum": ["是", "否"]
        },
        "continue_reason": {
            "type": "string",
            "description": "为什么要继续搜索/改变策略的原因"
        },
        "this_round_goal": {
            "type": "string",
            "description": "下一轮想要搜什么"
        },
        "this_query": {
            "type": "string",
            "description": "下一轮建议使用的搜索词"
        },
        "category_adjust_reason": {
            "type": "string"
        },
        "language_adjust_reason": {
            "type": "string"
        },
        "time_range_adjust_reason": {
            "type": "string"
        }
    }
}


# ============================================================
# 搜索工具的 parameters_schema 构建函数
# ============================================================


def build_web_search_schema(concurrent_requests: int = _DEFAULT_CONCURRENT_REQUESTS) -> dict[str, Any]:
    """
    构建搜索工具的 parameters_schema。

    做什么：根据并发请求数量动态设置 query 外层数组的长度约束。
            外层数组有 concurrent_requests 个子数组，每个子数组包含该并发请求要同时搜索的多个关键词。
    为什么这样做：query 外层数组长度必须与 concurrent_requests 配置值严格相等，
                通过 Schema 级别的 minItems/maxItems 约束可以在调用方就完成校验。
    参数:
        concurrent_requests: 并发请求数量，同时也是 query 外层数组的期望长度。
    返回:
        dict: 包含参数约束的 JSON Schema。
    """
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "minItems": 1,
                    "maxItems": 50,
                    "description": "该并发请求要同时使用的多个搜索词。"
                                   "例如：['2024年诺贝尔奖获得者', 'Nobel Prize winners 2024']。",
                },
                "minItems": concurrent_requests,
                "maxItems": concurrent_requests,
                "description": (
                    f"搜索查询关键词外层数组。必填。外层数组数量必须为 {concurrent_requests}，"
                    f"其中每个内层数组包含该并发请求要同时使用的多个搜索词。"
                ),
            },
            "categories": {
                "type": "string",
                "description": "搜索分类筛选，可选。多个分类用逗号分隔。"
                               "可选值：general, news, images, videos, files, music, it, science,"
                               "  social media。默认：general。例如：'general,news'。",
                "default": "general",
            },
            "language": {
                "type": "string",
                "description": "搜索结果语言过滤，可选。使用 ISO 639-1 语言代码。"
                               "例如：'zh-CN'（简体中文）、'en-US'（美式英语）。"
                               "默认：'zh-CN'。",
                "default": "zh-CN",
            },
            "time_range": {
                "type": "string",
                "enum": [
                    "",
                    "day",
                    "month",
                    "year",
                ],
                "default": "",
                "description": "时间范围过滤"
            }
        },
        "required": ["query"],
    }


# 保留向后兼容的静态常量，默认使用 _DEFAULT_CONCURRENT_REQUESTS 构建
SEARXNG_SEARCH_PARAMETERS_SCHEMA: dict[str, Any] = build_web_search_schema()


# ============================================================
# 辅助方法：单个搜索词的自动翻页爬取
# ============================================================


async def _fetch_for_single_term(
    term: str,
    search_params_template: dict[str, Any],
    base_url: str,
    timeout: float,
    results_per_request: int,
    trace_id: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    对单个搜索词进行自动翻页爬取，直到满足条数。

    做什么：对单个搜索词发起 SearXNG 请求，若当前页返回结果不足则自动递增 pageno 继续请求。
            翻页过程中对结果做 URL 维度去重，避免同一条结果被重复收集。
    为什么这样做：最大化单次搜索的搜索结果获取效率，不需要外部配置页码上限，持续翻页直至收集足够结果。
    参数:
        term: 具体的搜索词。
        search_params_template: 公共请求参数字典（不含 q 和 pageno）。
        base_url: SearXNG 实例地址。
        timeout: 单次 HTTP 请求超时秒数。
        results_per_request: 期望收集到的结果数上限。
        trace_id: 全链路追踪 ID。
    返回:
        (term, collected_results, collected_infoboxes) 三元组。
    边界条件:
        - 任何一级异常（超时、连接失败、JSON 解析错误）都会中断当前搜索词的翻页循环。
        - 本页无新结果（全部已去重）时提前终止该词的翻页。
    """
    collected_results: list[dict[str, Any]] = []
    collected_infoboxes: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    current_page = 1
    while len(collected_results) < results_per_request:
        params = search_params_template.copy()
        params["q"] = term
        params["pageno"] = current_page

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"{base_url}/search",
                    params=params,
                    headers={
                        "User-Agent": "Luna-AI/1.0 (Web Search Skill; +https://github.com/luna-ai)",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()

                results = data.get("results", [])
                infoboxes = data.get("infoboxes", [])

                # 去重合并 infoboxes
                for box in infoboxes:
                    title = box.get("infobox", box.get("title", ""))
                    if title and title not in [
                        b.get("infobox", b.get("title", "")) for b in collected_infoboxes
                    ]:
                        collected_infoboxes.append(box)

                # 去重合并 results
                new_results_added = False
                for r in results:
                    url = r.get("url")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        collected_results.append(r)
                        new_results_added = True
                        if len(collected_results) >= results_per_request:
                            break

                # 如果本页没有任何新结果或结果集为空，则提前终止本词搜索
                if not new_results_added and not results:
                    break

                current_page += 1

        except Exception as exc:
            logger.warning(
                f"SearXNG 单个搜索词异常 trace_id={trace_id} "
                f"term={term} page={current_page} error={exc!s}"
            )
            break

    return term, collected_results, collected_infoboxes


async def _fetch_for_request_group(
    terms: list[str],
    search_params_template: dict[str, Any],
    base_url: str,
    timeout: float,
    results_per_request: int,
    trace_id: str,
    group_index: int,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    对一个并发请求组进行搜索：组内多个搜索词各自搜索后再合并去重。

    做什么：一个并发请求组包含多个搜索词，逐个搜索这些词，然后将所有结果合并去重后返回。
            翻页逻辑在单词级别进行（_fetch_for_single_term）。
    为什么这样做：一个并发请求可以同时使用多个搜索词从不同角度覆盖同一主题，
                最大化该并发请求的信息获取效率。
    参数:
        terms: 该组的多个搜索词，组内顺序搜索并合并。
        group_index: 当前组在并发数组中的序号，用于日志。
        其余参数见 _fetch_for_single_term。
    返回:
        (group_index, merged_results, merged_infoboxes) 三元组。
    """
    group_results: list[dict[str, Any]] = []
    group_infoboxes: list[dict[str, Any]] = []
    seen_urls_in_group: set[str] = set()
    seen_infobox_titles_in_group: set[str] = set()

    # 组内多个搜索词并发搜索，然后合并去重
    term_tasks = [
        _fetch_for_single_term(
            term, search_params_template, base_url, timeout,
            results_per_request, trace_id,
        )
        for term in terms
    ]
    term_results_list = await asyncio.gather(*term_tasks, return_exceptions=True)

    for term_item in term_results_list:
        if isinstance(term_item, Exception):
            logger.warning(
                f"SearXNG 请求组内搜索词异常 trace_id={trace_id} "
                f"group={group_index} error={term_item!s}"
            )
            continue
        _, term_results, term_infoboxes = term_item
        for r in term_results:
            url = r.get("url")
            if url and url not in seen_urls_in_group:
                seen_urls_in_group.add(url)
                group_results.append(r)

        for box in term_infoboxes:
            title = box.get("infobox", box.get("title", ""))
            if title and title not in seen_infobox_titles_in_group:
                seen_infobox_titles_in_group.add(title)
                group_infoboxes.append(box)

    return group_index, group_results, group_infoboxes


# ============================================================
# 工具执行 Handler
# ============================================================


async def handle_searxng_search(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    通过 SearXNG 执行网络搜索的工具 handler。

    做什么：支持并发和自动翻页的高级 Web 搜索逻辑。query 为外层数组，长度等于 concurrent_requests，
            每个内层数组包含该并发请求要同时使用的多个搜索词。通过异步并发机制对外层数组的
            每个子组发起请求；在每个子组内部，按搜索词逐一搜索并合并去重；对每个搜索词，
            自动递增 pageno（页码）收集足量数据。
    为什么这样做：通过并行化和自动翻页最大化搜索结果的获取效率，提高信息获取质量。
    参数:
        parameters: 包含以下字段的字典：
            - query（必填）：外层数组，每个内层数组为一个搜索组，包含该组要同时使用的多个搜索词。
            - categories（可选）：搜索分类，多个用逗号分隔。
            - language（可选）：语言过滤代码。
            - time_range（可选）：时间过滤。
        trace_id: 全链路追踪 ID。
    返回:
        str: 格式化后的搜索结果文本。
    边界条件:
        - SearXNG 服务不可达或超时时返回友好错误提示，不影响主流程。
        - 搜索结果为空时返回"未找到相关结果"提示。
        - 输出超出 max_url_fetch_length 字符时截断标记。
    """
    # ============================================================
    # 前置检查：从 ToolConfigManager 读取 SearXNG 配置
    # ============================================================
    config_mgr = ToolConfigManager()
    tool_config = config_mgr.get_config(TOOL_NAME)
    base_url: str = tool_config.get(CONFIG_KEY_BASE_URL, "")
    timeout = _safe_float(tool_config.get(CONFIG_KEY_TIMEOUT), _SEARXNG_DEFAULT_TIMEOUT)
    concurrent_requests = _safe_int(
        tool_config.get(CONFIG_KEY_CONCURRENT_REQUESTS),
        _DEFAULT_CONCURRENT_REQUESTS,
        minimum=1,
        maximum=10,
    )
    results_per_request = _safe_int(
        tool_config.get(CONFIG_KEY_RESULTS_PER_REQUEST),
        _DEFAULT_RESULTS_PER_REQUEST,
        minimum=1,
        maximum=50,
    )
    max_url_fetch_length = _safe_int(
        tool_config.get(CONFIG_KEY_MAX_URL_FETCH_LENGTH),
        _DEFAULT_MAX_URL_FETCH_LENGTH,
        minimum=1000,
    )
    safe_search_level = _safe_int(
        tool_config.get(CONFIG_KEY_SAFE_SEARCH_LEVEL),
        _DEFAULT_SAFE_SEARCH_LEVEL,
        minimum=0,
        maximum=2,
    )

    if not base_url:
        logger.warning(
            f"SearXNG 搜索失败 trace_id={trace_id} "
            f"原因: web_search 工具未配置 base_url"
        )
        return (
            "【SearXNG 搜索配置错误】\n"
            "SearXNG 实例 URL 未配置。请在 Luna 面板的 "
            "「MCP Skill → web_search 工具」中点击配置按钮设置 base_url。\n"
            "例如：http://localhost:8888"
        )

    # 去除 URL 末尾的斜杠
    base_url = base_url.rstrip("/")

    # ============================================================
    # 提取参数
    # ============================================================
    # query 为外层数组，长度等于 concurrent_requests
    # 每个内层数组包含该并发请求要同时使用的多个搜索词
    query = parameters.get("query")
    if not query or not isinstance(query, list):
        return "【搜索参数错误】搜索查询词（query）必须是非空外层数组。"

    # 校验外层数组长度必须与并发请求数量一致
    if len(query) != concurrent_requests:
        return (
            f"【搜索参数错误】搜索查询词外层数组长度必须与'并发请求数量'配置一致。"
            f"当前外层数组长度: {len(query)}，配置的并发请求数量: {concurrent_requests}。"
            f"请调整查询词组数量或修改'并发请求数量'配置。"
        )

    # 清理并校验每个内层数组
    query_groups: list[list[str]] = []
    for group_idx, group in enumerate(query):
        if not isinstance(group, list):
            return (
                f"【搜索参数错误】query[{group_idx}] 必须是数组。"
            )
        cleaned_terms: list[str] = []
        seen_terms_in_group: set[str] = set()
        for t in group:
            if isinstance(t, str):
                t_stripped = t.strip()
                if t_stripped and t_stripped not in seen_terms_in_group:
                    seen_terms_in_group.add(t_stripped)
                    cleaned_terms.append(t_stripped)
        if not cleaned_terms:
            return (
                f"【搜索参数错误】query[{group_idx}] 内层数组中没有有效的搜索词。"
            )
        query_groups.append(cleaned_terms)

    categories: str = parameters.get("categories", "general")
    language: str = parameters.get("language", "zh-CN")
    time_range: str = parameters.get("time_range", "")

    # ============================================================
    # 构造核心模板参数
    # ============================================================
    search_params_template: dict[str, Any] = {
        "format": "json",
        "categories": categories,
        "language": language,
        "safesearch": safe_search_level,
    }

    if time_range:
        search_params_template["time_range"] = time_range

    logger.info(
        f"SearXNG 高级搜索请求 trace_id={trace_id} "
        f"concurrent_groups={concurrent_requests} "
        f"query_groups={query_groups} "
        f"results_per_request={results_per_request}"
    )

    # ============================================================
    # 并发请求与自动翻页
    # ============================================================
    # 与 concurrent_requests 一致的并发数，每个并发任务处理一个 query 组
    tasks = [
        _fetch_for_request_group(
            terms,
            search_params_template,
            base_url,
            timeout,
            results_per_request,
            trace_id,
            group_idx,
        )
        for group_idx, terms in enumerate(query_groups)
    ]

    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    # ============================================================
    # 合并所有并发组的结果（全局去重）
    # ============================================================
    all_results: list[dict[str, Any]] = []
    all_infoboxes: list[dict[str, Any]] = []
    seen_urls_global: set[str] = set()
    seen_infobox_titles_global: set[str] = set()

    for item in results_list:
        if isinstance(item, Exception):
            logger.warning(
                f"SearXNG 并发请求组异常 trace_id={trace_id} error={item!s}"
            )
            continue

        _group_idx, group_results, group_infoboxes = item
        for r in group_results:
            url = r.get("url")
            if url and url not in seen_urls_global:
                seen_urls_global.add(url)
                all_results.append(r)

        for box in group_infoboxes:
            title = box.get("infobox", box.get("title", ""))
            if title and title not in seen_infobox_titles_global:
                seen_infobox_titles_global.add(title)
                all_infoboxes.append(box)

    if not all_results and not all_infoboxes:
        logger.info(
            f"SearXNG 搜索无结果 trace_id={trace_id} "
            f"query_groups={query_groups}"
        )
        # 将所有搜索词展平后显示
        all_terms = [t for g in query_groups for t in g]
        return f"【未找到相关结果】\n查询词：{', '.join(all_terms)}\n"

    # ============================================================
    # 格式化输出
    # ============================================================
    output_parts: list[str] = []
    # 将所有搜索词展平以显示
    all_terms_flat = [t for g in query_groups for t in g]
    output_parts.append(f"【搜索结果】查询词：{', '.join(all_terms_flat)}")
    output_parts.append(
        f"并发 {concurrent_requests} 组搜索，共获取 {len(all_results)} 条常规结果与 "
        f"{len(all_infoboxes)} 条知识卡片"
    )
    output_parts.append("")

    # 信息框（知识卡片）
    for box in all_infoboxes:
        box_title: str = box.get("infobox", box.get("title", ""))
        box_content: str = box.get("content", "")
        box_urls: list[dict[str, str]] = box.get("urls", [])
        if box_title:
            output_parts.append(f"📋 【知识卡片】{box_title}")
            if box_content:
                output_parts.append(f"   {box_content}")
            for url_entry in box_urls:
                url_title: str = url_entry.get("title", "")
                url_link: str = url_entry.get("url", "")
                if url_title and url_link:
                    output_parts.append(f"   🔗 {url_title}: {url_link}")
            # 信息框属性
            attributes: list[dict[str, str]] = box.get("attributes", [])
            for attr in attributes:
                attr_label: str = attr.get("label", "")
                attr_value: str = attr.get("value", "")
                if attr_label and attr_value:
                    output_parts.append(f"   • {attr_label}: {attr_value}")
            output_parts.append("")

    # 常规搜索结果
    for idx, result in enumerate(all_results, 1):
        title: str = result.get("title", "无标题")
        url: str = result.get("url", "")
        content: str = result.get("content", "")
        engine: str = result.get("engine", "")

        output_parts.append(f"{idx}. {title}")
        if content:
            # 单条内容截断到 300 字符
            content_snippet = content[:300] + ("..." if len(content) > 300 else "")
            output_parts.append(f"   {content_snippet}")
        if url:
            output_parts.append(f"   来源: {url}")
        if engine:
            output_parts.append(f"   引擎: {engine}")
        output_parts.append("")

    output_text: str = "\n".join(output_parts)

    # 输出长度截断
    if len(output_text) > max_url_fetch_length:
        output_text = output_text[:max_url_fetch_length] + "\n\n[truncated]"

    logger.info(
        f"SearXNG 搜索成功 trace_id={trace_id} "
        f"concurrent_groups={concurrent_requests} "
        f"groups_results={[len(r) if not isinstance(r, Exception) else 0 for r in results_list]}"
        f" total_results={len(all_results)} "
        f"total_infoboxes={len(all_infoboxes)} output_length={len(output_text)}"
    )

    return output_text


def _safe_float(
    value: Any,
    default: float,
) -> float:
    """安全转换为 float，转换失败返回默认值"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(
    value: Any,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """安全转换为 int，支持范围约束"""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result
