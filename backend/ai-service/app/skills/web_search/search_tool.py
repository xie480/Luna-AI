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
CONFIG_KEY_RESULTS_PER_REQUEST: str = "results_per_request"         # 每个请求的搜索结果数量
CONFIG_KEY_MAX_URL_FETCH_LENGTH: str = "max_url_fetch_length"       # URL抓取内容长度上限
CONFIG_KEY_SAFE_SEARCH_LEVEL: str = "safe_search_level"             # 安全搜索级别


# ============================================================
# 常量定义
# ============================================================

_SEARXNG_DEFAULT_TIMEOUT: float = 15.0
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
            "description": "刚尝试搜索的关键词列表"
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
            "description": "下一轮建议使用的搜索词列表"
        },
        "time_range_adjust_reason": {
            "type": "string"
        }
    }
}


# ============================================================
# ============================================================
# 搜索策略模板定义
# ============================================================
# 做什么：定义 3 种差异化搜索策略，每个搜索词会同时以这 3 种策略并发执行。
#         结果全局去重合并后返回。
# 为什么这样做：
#   1. 降低 LLM 输出复杂度 — LLM 只需输出一维搜索词列表，不需关心并发分组和搜索策略。
#   2. 保证结果多样性 — 3 个策略在 categories 和 language 两个维度正交，
#      从中文通用、中文新闻、英文通用三个角度覆盖同一主题，最大化信息获取质量。
#   3. 行为确定性 — 搜索策略由代码层控制，不依赖 LLM 的"理解"，一致性 100%。
#
# 三个策略的定位：
#   - zh_general: 中文通用搜索（全引擎覆盖），覆盖面最广，是主力搜索路径。
#   - zh_news:    中文新闻搜索（新闻专用引擎），针对新闻/时事内容，
#                  Google News、Bing News 等返回的结果包含发布日期和来源媒体。
#   - en_general: 英文通用搜索（补充覆盖），很多技术、学术、国际事件的高质量信息
#                  只有英文来源。
_SEARCH_STRATEGIES: list[dict[str, str]] = [
    {
        "name": "zh_general",
        "description": "中文通用搜索（全引擎覆盖）",
        "categories": "",
        "language": "zh-CN",
    },
    {
        "name": "zh_news",
        "description": "中文新闻搜索（新闻专用引擎）",
        "categories": "news",
        "language": "zh-CN",
    },
    {
        "name": "en_general",
        "description": "英文通用搜索（补充覆盖）",
        "categories": "",
        "language": "en",
    },
]


# 搜索工具的 parameters_schema 构建函数
# ============================================================


def build_web_search_schema() -> dict[str, Any]:
    """
    构建搜索工具的 parameters_schema。

    做什么：定义一维搜索词数组 Schema。LLM 只需输出搜索词列表，
            工具 handler 会自动对每个搜索词执行多策略并发搜索。
    为什么这样做：简化 LLM 输出结构为一维数组，将"搜索策略多样化"这个
                工程策略下沉到代码层自动执行，消除嵌套数组导致的格式错误。
    返回:
        dict: 包含参数约束的 JSON Schema。
    """
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "array",
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "minItems": 1,
                "maxItems": 10,
                "description": (
                    "搜索查询关键词列表（一维数组）。必填。工具会自动对每个关键词执行"
                    "多策略并发搜索（中文通用、中文新闻、英文通用），结果自动去重合并。"
                    "建议提供 2-5 个不同角度的搜索词。"
                    "示例：['2026世界杯 赛程', 'FIFA World Cup 2026', '世界杯 战报']。"
                ),
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
                "description": (
                    "时间范围过滤。可选。"
                    "'day'=24小时内，'month'=一个月内，'year'=一年内，空字符串=不限。"
                ),
            },
        },
        "required": ["query"],
    }


# 向后兼容的静态常量
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

        # 调试日志：记录实际发送的请求参数
        logger.info(
            f"SearXNG 请求详情 trace_id={trace_id} "
            f"term={term} page={current_page} "
            f"request_url={base_url}/search "
            f"params={params}"
        )

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

                # 调试日志：记录 SearXNG 返回的原始响应摘要
                # 特别关注 unresponsive_engines 字段，它记录了哪些引擎响应失败
                unresponsive = data.get("unresponsive_engines", [])
                logger.info(
                    f"SearXNG 响应详情 trace_id={trace_id} "
                    f"term={term} page={current_page} "
                    f"status_code={response.status_code} "
                    f"response_keys={list(data.keys()) if isinstance(data, dict) else 'N/A'} "
                    f"results_count={len(data.get('results', []))} "
                    f"infoboxes_count={len(data.get('infoboxes', []))} "
                    f"number_of_results={data.get('number_of_results', 'N/A')} "
                    f"unresponsive_engines={unresponsive if unresponsive else '无'}"
                )

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
            # 记录更详细的异常信息，区分超时、连接错误和 HTTP 错误
            import httpx as _httpx
            exc_detail = f"type={type(exc).__name__} error={exc!s}"
            if isinstance(exc, _httpx.TimeoutException):
                exc_detail = f"超时 timeout={timeout}s {exc_detail}"
            elif isinstance(exc, _httpx.HTTPStatusError):
                exc_detail = (
                    f"HTTP 错误 status={exc.response.status_code} "
                    f"response_body={exc.response.text[:500]} {exc_detail}"
                )
            elif isinstance(exc, _httpx.ConnectError):
                exc_detail = f"连接失败 base_url={base_url} {exc_detail}"

            logger.warning(
                f"SearXNG 单个搜索词异常 trace_id={trace_id} "
                f"term={term} page={current_page} "
                f"request_url={base_url}/search "
                f"params={params} "
                f"{exc_detail}"
            )
            break

    return term, collected_results, collected_infoboxes


# ============================================================
# 工具执行 Handler（多策略并发搜索）
# ============================================================


async def handle_searxng_search(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    通过 SearXNG 执行网络搜索的工具 handler。

    做什么：接收一维搜索词列表，自动对每个搜索词以 3 种差异化策略（中文通用、
            中文新闻、英文通用）并发执行搜索，所有结果全局去重后合并返回。
            每个搜索词在每个策略下自动翻页获取足量结果。
    为什么这样做：将"搜索策略多样化"从 LLM 层下沉到代码层自动执行，
                降低 LLM 输出复杂度（只需一维数组），同时保证结果多样性和行为确定性。
    参数:
        parameters: 包含以下字段的字典：
            - query（必填）：一维搜索词字符串数组，如 ['关键词1', '关键词2']。
            - time_range（可选）：时间过滤，可选值为 '' / 'day' / 'month' / 'year'。
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

    base_url = base_url.rstrip("/")

    # ============================================================
    # 提取并清理一维搜索词列表
    # ============================================================
    raw_query = parameters.get("query")
    if not raw_query or not isinstance(raw_query, list):
        return "【搜索参数错误】搜索查询词（query）必须是非空数组。"

    # 清理搜索词：去空、去重、保持顺序
    query_terms: list[str] = []
    seen_terms: set[str] = set()
    for t in raw_query:
        if isinstance(t, str):
            t_stripped = t.strip()
            if t_stripped and t_stripped not in seen_terms:
                seen_terms.add(t_stripped)
                query_terms.append(t_stripped)

    if not query_terms:
        return "【搜索参数错误】query 数组中没有有效的搜索词。"

    time_range: str = parameters.get("time_range", "")

    # ============================================================
    # 构建并发任务：每个搜索词 × 每个策略
    # ============================================================
    # 为每个策略构建 SearXNG 请求参数模板
    # 注意：SearXNG 不接受空字符串参数值，传递空值参数会导致 400 Bad Request。
    # 因此只在参数有值时加入字典。
    strategy_param_templates: list[dict[str, Any]] = []
    for strategy in _SEARCH_STRATEGIES:
        template: dict[str, Any] = {
            "format": "json",
            "safesearch": safe_search_level,
        }
        if strategy.get("categories"):
            template["categories"] = strategy["categories"]
        if strategy.get("language"):
            template["language"] = strategy["language"]
        if time_range and time_range.strip():
            template["time_range"] = time_range.strip()
        strategy_param_templates.append(template)

    # 构建并发任务：每个搜索词 × 每个策略 = len(query_terms) * len(_SEARCH_STRATEGIES) 个任务
    tasks = []
    task_meta: list[tuple[str, str]] = []  # (term, strategy_name) 用于日志
    for term in query_terms:
        for idx, strategy in enumerate(_SEARCH_STRATEGIES):
            tasks.append(
                _fetch_for_single_term(
                    term, strategy_param_templates[idx], base_url, timeout,
                    results_per_request, trace_id,
                )
            )
            task_meta.append((term, strategy["name"]))

    logger.info(
        f"SearXNG 多策略搜索请求 trace_id={trace_id} "
        f"base_url={base_url} "
        f"query_terms={query_terms} "
        f"strategies={[s['name'] for s in _SEARCH_STRATEGIES]} "
        f"total_tasks={len(tasks)} "
        f"results_per_request={results_per_request} "
        f"timeout={timeout} "
        f"time_range={time_range}"
    )

    # 并发执行所有任务
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    # ============================================================
    # 全局去重合并
    # ============================================================
    all_results: list[dict[str, Any]] = []
    all_infoboxes: list[dict[str, Any]] = []
    seen_urls_global: set[str] = set()
    seen_infobox_titles_global: set[str] = set()

    for idx, item in enumerate(results_list):
        if isinstance(item, Exception):
            term, strategy_name = task_meta[idx] if idx < len(task_meta) else ("?", "?")
            logger.warning(
                f"SearXNG 任务异常 trace_id={trace_id} "
                f"term={term} strategy={strategy_name} error={item!s}"
            )
            continue

        _term, term_results, term_infoboxes = item
        for r in term_results:
            url = r.get("url")
            if url and url not in seen_urls_global:
                seen_urls_global.add(url)
                all_results.append(r)

        for box in term_infoboxes:
            title = box.get("infobox", box.get("title", ""))
            if title and title not in seen_infobox_titles_global:
                seen_infobox_titles_global.add(title)
                all_infoboxes.append(box)

    if not all_results and not all_infoboxes:
        logger.info(
            f"SearXNG 搜索无结果 trace_id={trace_id} "
            f"query_terms={query_terms}"
        )
        return f"【未找到相关结果】\n查询词：{', '.join(query_terms)}\n"

    # ============================================================
    # 格式化输出
    # ============================================================
    output_parts: list[str] = []
    strategy_names = "、".join(s["name"] for s in _SEARCH_STRATEGIES)
    output_parts.append(f"【搜索结果】查询词：{', '.join(query_terms)}")
    output_parts.append(
        f"多策略并发搜索（{strategy_names}），共获取 "
        f"{len(all_results)} 条常规结果与 {len(all_infoboxes)} 条知识卡片"
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
            content_snippet = content[:300] + ("..." if len(content) > 300 else "")
            output_parts.append(f"   {content_snippet}")
        if url:
            output_parts.append(f"   来源: {url}")
        if engine:
            output_parts.append(f"   引擎: {engine}")
        output_parts.append("")

    output_text: str = "\n".join(output_parts)

    logger.info(
        f"SearXNG 多策略搜索成功 trace_id={trace_id} "
        f"query_terms={query_terms} "
        f"strategies={[s['name'] for s in _SEARCH_STRATEGIES]} "
        f"total_tasks={len(tasks)} "
        f"total_results={len(all_results)} "
        f"total_infoboxes={len(all_infoboxes)} "
        f"output_length={len(output_text)}"
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
