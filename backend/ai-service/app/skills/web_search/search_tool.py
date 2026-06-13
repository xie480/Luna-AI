"""
MCP 内置工具：通过 SearXNG 执行网络搜索。

做什么：提供通过 SearXNG 搜索引擎实例执行网络搜索的工具实现。
        支持自定义查询、分类筛选、引擎选择、语言过滤和分页。
        作为 L0 级低危工具（仅发起只读 HTTP GET 请求），直接放行无需用户确认。
为什么这样做：Phase 12 需要接入至少一个具备实际能力的数据获取工具来验证
              工具链路在数据获取场景下的完整性。SearXNG 作为自托管的元搜索引擎，
              满足本地优先原则，无需依赖第三方搜索 API 密钥。
边界条件：
    - 依赖本地或局域网部署的 SearXNG 实例，URL 通过 ToolConfig 配置。
    - 用户在前端 Skill 面板的 web_search 工具条目中，点击"配置"按钮设置。
    - SearXNG 实例必须启用 JSON API（通过 searxng.yml 配置）。
    - 请求超时由工具配置中的 timeout 控制，默认 15 秒。
    - 搜索失败时返回友好错误提示，不影响主流程。
    - 输出文本裁剪到最大 8192 字符，超出部分截断标记 [truncated]。
"""

from __future__ import annotations

import json
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
CONFIG_KEY_BASE_URL: str = "base_url"   # SearXNG 实例基础 URL
CONFIG_KEY_TIMEOUT: str = "timeout"     # 请求超时秒数


# ============================================================
# 常量定义
# ============================================================

# SearXNG JSON API 默认请求超时（秒）
_SEARXNG_DEFAULT_TIMEOUT: float = 15.0

# 搜索结果输出最大字符数
_SEARXNG_OUTPUT_MAX_CHARS: int = 8192


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
        "previous_pageno": {
            "type": "integer"
        },
        "previous_engines": {
            "type": "string"
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
        },
        "need_specific_engine": {
            "type": "string",
            "enum": ["是", "否"]
        }
    }
}


# ============================================================
# 搜索工具的 parameters_schema（JSON Schema 格式）
# ============================================================

SEARXNG_SEARCH_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "搜索查询关键词。必填。例如：'2024年诺贝尔奖获得者'。",
        },
        "categories": {
            "type": "string",
            "description": "搜索分类筛选，可选。多个分类用逗号分隔。"
                           "可选值：general, news, images, videos, files, music, it, science,"
                           "  social media。默认：general。例如：'general,news'。",
            "default": "general",
        },
        "engines": {
            "type": "string",
            "description": "指定使用的搜索引擎，可选。多个引擎用逗号分隔。"
                           "例如：'google,bing,duckduckgo'。不指定则使用 SearXNG 默认引擎。",
            "default": "",
        },
        "language": {
            "type": "string",
            "description": "搜索结果语言过滤，可选。使用 ISO 639-1 语言代码。"
                           "例如：'zh-CN'（简体中文）、'en-US'（美式英语）。"
                           "默认：'zh-CN'。",
            "default": "zh-CN",
        },
        "pageno": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "搜索结果页码，可选。从 1 开始，默认：1。",
            "default": 1,
        },
        "safesearch": {
            "type": "integer",
            "enum": [0, 1, 2],
            "description": "安全搜索级别，可选。0=关闭，1=中等，2=严格。默认：1。",
            "default": 1,
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "返回的最大结果数量，可选。默认：10，最大：50。",
            "default": 10,
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


# ============================================================
# 工具执行 Handler
# ============================================================


async def handle_searxng_search(
    parameters: dict[str, Any],
    trace_id: str,
) -> str:
    """
    通过 SearXNG 执行网络搜索的工具 handler。

    做什么：根据传入的搜索参数，向配置的 SearXNG 实例发起 JSON API 请求，
            获取搜索结果后格式化为可读文本返回。支持分类、引擎、语言等筛选。
    为什么这样做：SearXNG 是自托管的元搜索引擎，聚合 Google、Bing、DuckDuckGo
                等主流搜索引擎的结果，满足本地优先的隐私保护需求。
    参数:
        parameters: 包含以下字段的字典：
            - query（必填）：搜索查询关键词。
            - categories（可选）：搜索分类，多个用逗号分隔。
            - engines（可选）：指定搜索引擎，多个用逗号分隔。
            - language（可选）：语言过滤代码。
            - pageno（可选）：页码。
            - safesearch（可选）：安全搜索级别。
            - max_results（可选）：最大返回结果数。
        trace_id: 全链路追踪 ID。
    返回:
        str: 格式化后的搜索结果文本。
    边界条件:
        - SEARXNG_BASE_URL 未配置时返回错误提示。
        - SearXNG 服务不可达或超时时返回友好错误提示。
        - 搜索结果为空时返回"未找到相关结果"提示。
        - 输出超出 _SEARXNG_OUTPUT_MAX_CHARS 字符时截断标记。
    """
    # ============================================================
    # 前置检查：从 ToolConfigManager 读取 SearXNG 配置
    # ============================================================
    config_mgr = ToolConfigManager()
    tool_config = config_mgr.get_config(TOOL_NAME)
    base_url: str = tool_config.get(CONFIG_KEY_BASE_URL, "")
    try:
        timeout = float(
            tool_config.get(
                CONFIG_KEY_TIMEOUT,
                _SEARXNG_DEFAULT_TIMEOUT,
            )
        )
    except (TypeError, ValueError):
        timeout = _SEARXNG_DEFAULT_TIMEOUT

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
    query = str(
        parameters.get("query", "")
    ).strip()
    if not query:
        return "【搜索参数错误】搜索查询词（query）不能为空。"

    categories: str = parameters.get("categories", "general")
    engines: str = parameters.get("engines", "")
    language: str = parameters.get("language", "zh-CN")
    time_range: str = parameters.get("time_range", "")
    pageno = _safe_int(
        parameters.get("pageno"),
        default=1,
        minimum=1,
        maximum=50,
    )

    safesearch = _safe_int(
        parameters.get("safesearch"),
        default=1,
        minimum=0,
        maximum=2,
    )

    max_results = _safe_int(
        parameters.get("max_results"),
        default=10,
        minimum=1,
        maximum=50,
    )

    # 参数校验
    if max_results < 1:
        max_results = 1
    elif max_results > 50:
        max_results = 50

    # ============================================================
    # 构造 HTTP 请求参数
    # ============================================================
    search_params: dict[str, Any] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": language,
        "pageno": pageno,
        "safesearch": safesearch,
    }

    if time_range:
        search_params["time_range"] = time_range

    # 可选参数：指定搜索引擎
    if engines:
        search_params["engines"] = engines

    logger.info(
        f"SearXNG 搜索请求 trace_id={trace_id} "
        f"query={query} categories={categories} "
        f"language={language} pageno={pageno}"
    )

    # ============================================================
    # 发起 HTTP 请求
    # ============================================================
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base_url}/search",
                params=search_params,
                headers={
                    "User-Agent": "Luna-AI/1.0 (Web Search Skill; +https://github.com/luna-ai)",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
    except httpx.TimeoutException:
        logger.warning(
            f"SearXNG 搜索超时 trace_id={trace_id} "
            f"query={query} timeout={timeout}s"
        )
        return (
            f"【搜索超时】SearXNG 实例在 {timeout} 秒内未响应。\n"
            f"查询词：{query}\n"
            f"请检查 SearXNG 服务是否正常运行，或稍后重试。"
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            f"SearXNG 搜索 HTTP 错误 trace_id={trace_id} "
            f"query={query} status_code={exc.response.status_code}"
        )
        return (
            f"【搜索服务错误】SearXNG 返回 HTTP {exc.response.status_code}。\n"
            f"查询词：{query}\n"
            f"请检查 SearXNG 实例配置是否正确。"
        )
    except httpx.RequestError as exc:
        logger.warning(
            f"SearXNG 搜索请求失败 trace_id={trace_id} "
            f"query={query} error={exc!s}"
        )
        return (
            f"【搜索请求失败】无法连接到 SearXNG 实例。\n"
            f"查询词：{query}\n"
            f"目标地址：{base_url}\n"
            f"错误信息：{exc!s}\n"
            f"请确认 SearXNG 服务已启动且网络可达。"
        )
    except json.JSONDecodeError:
        logger.warning(
            f"SearXNG 搜索响应解析失败 trace_id={trace_id} "
            f"query={query} 原因: 响应不是合法 JSON"
        )
        return (
            f"【搜索结果解析错误】SearXNG 返回了非预期的响应格式。\n"
            f"查询词：{query}\n"
            f"请确认 SearXNG 已启用 JSON API（在 searxng.yml 中设置"
            f" search: {format: json}）。"
        )
    except Exception as exc:
        logger.warning(
            f"SearXNG 搜索异常 trace_id={trace_id} "
            f"query={query} error={exc!s}"
        )
        return (
            f"【搜索异常】执行搜索时发生未知错误。\n"
            f"查询词：{query}\n"
            f"错误信息：{exc!s}"
        )

    # ============================================================
    # 解析搜索结果
    # ============================================================
    results: list[dict[str, Any]] = data.get("results", [])
    suggestions: list[str] = data.get("suggestions", [])
    infoboxes: list[dict[str, Any]] = data.get("infoboxes", [])
    number_of_results: int = data.get("number_of_results", 0)

    # 按 max_results 截断
    results = results[:max_results]

    # 如果没有结果，返回提示
    if not results and not infoboxes:
        output: str = f"【未找到相关结果】\n查询词：{query}\n"
        if suggestions:
            output += "\n【搜索建议】\n您是否想搜索：\n"
            for idx, sug in enumerate(suggestions[:5], 1):
                output += f"  {idx}. {sug}\n"
        logger.info(
            f"SearXNG 搜索无结果 trace_id={trace_id} "
            f"query={query} suggestions={len(suggestions)}"
        )
        return output

    # ============================================================
    # 格式化输出
    # ============================================================
    output_parts: list[str] = []
    output_parts.append(f"【搜索结果】查询词：{query}")
    if number_of_results:
        output_parts.append(f"约 {number_of_results} 条结果，显示前 {len(results)} 条")
    output_parts.append("")

    # 信息框（知识卡片）
    for box in infoboxes:
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
    for idx, result in enumerate(results, 1):
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

    # 搜索建议
    if suggestions:
        output_parts.append("【相关搜索建议】")
        for idx, sug in enumerate(suggestions[:5], 1):
            output_parts.append(f"  {idx}. {sug}")
        output_parts.append("")

    output_text: str = "\n".join(output_parts)

    # 输出长度截断
    if len(output_text) > _SEARXNG_OUTPUT_MAX_CHARS:
        output_text = output_text[:_SEARXNG_OUTPUT_MAX_CHARS] + "\n\n[truncated]"

    logger.info(
        f"SearXNG 搜索成功 trace_id={trace_id} "
        f"query={query} results={len(results)} "
        f"infoboxes={len(infoboxes)} output_length={len(output_text)}"
    )

    return output_text

def _safe_int(
    value: Any,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result