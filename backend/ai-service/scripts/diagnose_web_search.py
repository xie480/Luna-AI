"""
SearXNG 搜索诊断脚本

做什么：模拟 handle_searxng_search 的请求参数直接调用 SearXNG API，
        逐步调整参数（移除 time_range、简化 query、调整 categories）
        以定位"搜不到结果"的根因。

使用方法：
    python scripts/diagnose_web_search.py

环境要求：
    - 需要与 SearXNG 实例网络可达（默认 http://192.168.100.128:8888）
    - 安装 httpx：pip install httpx
"""

import io
import sys

# 强制 stdout/stderr 使用 UTF-8 编码，避免 Windows 控制台 GBK 编码报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import json
import time
from typing import Any

import httpx

# ============================================================
# 配置
# ============================================================

# SearXNG 实例地址（从日志中提取）
BASE_URL: str = "http://192.168.100.128:8888"
# 请求超时（秒）
TIMEOUT: float = 15.0
# 安全搜索级别
SAFESEARCH: int = 0


def print_sep(title: str = "") -> None:
    """打印分隔线"""
    print(f"\n{'='*60}")
    if title:
        print(f"[{title}]")
        print(f"{'='*60}")


async def check_searxng_health(client: httpx.AsyncClient) -> None:
    """
    检查 SearXNG 实例的可用性，包括：
    - 首页 / 是否可达
    - /health 或 /config 端点（如果可以）
    - 搜索 API 的原始返回结构（查看是否有 engines 信息）
    """
    print_sep("检查 SearXNG 实例可用性")

    # 1. 检查首页
    try:
        resp = await client.get(
            BASE_URL,
            headers={"User-Agent": "Luna-AI/1.0 (Diagnostic)"},
            timeout=5.0,
        )
        print(f"  首页状态码: {resp.status_code}")
        print(f"  首页内容长度: {len(resp.text)} 字符")
        # 打印前500字符
        print(f"  首页预览: {resp.text[:500]}")
    except Exception as e:
        print(f"  [错误] 首页不可达: {e}")

    # 2. 尝试访问 /config 或 /health
    for endpoint in ["/health", "/config", "/about", "/stats"]:
        try:
            resp = await client.get(
                f"{BASE_URL}{endpoint}",
                headers={"User-Agent": "Luna-AI/1.0 (Diagnostic)"},
                timeout=5.0,
            )
            print(f"  {endpoint} 状态码: {resp.status_code}")
            if resp.status_code == 200:
                preview = resp.text[:800]
                print(f"  {endpoint} 内容: {preview}")
        except Exception as e:
            print(f"  {endpoint} 错误: {e}")

    # 3. 搜索 API 返回完整结构打印（搜索空字符串看返回什么）
    try:
        resp = await client.get(
            f"{BASE_URL}/search",
            params={"format": "json", "q": "test", "pageno": 1},
            headers={
                "User-Agent": "Luna-AI/1.0 (Diagnostic)",
                "Accept": "application/json",
            },
            timeout=10.0,
        )
        print(f"\n  搜索 API 状态码: {resp.status_code}")
        data = resp.json()
        print(f"  搜索 API 返回顶层 keys: {list(data.keys())}")

        # 打印 engines 信息（如果有）
        if "engines" in data:
            print(f"  可用引擎: {json.dumps(data['engines'], ensure_ascii=False, indent=2)[:1000]}")
        else:
            print("  [注意] 响应中无 engines 字段")

        # 打印未经过滤的原始 results 结构（哪怕为空）
        results = data.get("results", [])
        print(f"  results 数量: {len(results)}")
        if results:
            print(f"  第一条结果 keys: {list(results[0].keys())}")

        # 打印所有其他字段
        for key, value in data.items():
            if key not in ("results", "infoboxes", "engines"):
                print(f"  字段 {key}: {json.dumps(value, ensure_ascii=False)[:500]}")

        # 打印 unresponsive_engines（如果有）
        if "unresponsive_engines" in data:
            print(f"  无响应引擎: {data['unresponsive_engines']}")

    except Exception as e:
        print(f"  搜索 API 错误: {e}")


async def single_search_debug(
    client: httpx.AsyncClient,
    label: str,
    query: str,
    categories: str = "general",
    time_range: str = "",
    pageno: int = 1,
    show_raw: bool = False,
) -> dict[str, Any]:
    """
    执行单次搜索，可选择打印原始 JSON 响应。
    """
    url = f"{BASE_URL}/search"
    params: dict[str, Any] = {
        "format": "json",
        "safesearch": SAFESEARCH,
        "q": query,
        "pageno": pageno,
    }
    if categories:
        params["categories"] = categories
    if time_range:
        params["time_range"] = time_range

    start_ts = time.time()
    try:
        response = await client.get(
            url,
            params=params,
            headers={
                "User-Agent": "Luna-AI/1.0 (Web Search Diagnostic)",
                "Accept": "application/json",
            },
        )
        elapsed_ms = int((time.time() - start_ts) * 1000)
        data: dict[str, Any] = response.json()
        results = data.get("results", [])
        infoboxes = data.get("infoboxes", [])
        suggestions = data.get("suggestions", [])
        answers = data.get("answers", [])

        raw_result = {
            "label": label,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "query": query,
            "categories": categories,
            "time_range": time_range,
            "pageno": pageno,
            "result_count": len(results),
            "infobox_count": len(infoboxes),
            "suggestion_count": len(suggestions),
            "answer_count": len(answers),
            "first_result_title": results[0].get("title", "") if results else "",
            "first_result_url": results[0].get("url", "") if results else "",
            "all_titles": [r.get("title", "") for r in results],
            "suggestions": suggestions,
            "answers": answers,
            "unresponsive_engines": data.get("unresponsive_engines", []),
            "engine_result_count": {},  # 每个引擎的结果数
        }

        # 统计每个引擎的结果数
        for r in results:
            eng = r.get("engine", "unknown")
            raw_result["engine_result_count"][eng] = raw_result["engine_result_count"].get(eng, 0) + 1

        if show_raw:
            # 打印完整的响应结构（排除过长的 content）
            debug_data = {}
            for k, v in data.items():
                if k == "results":
                    debug_data[k] = [
                        {kk: vv for kk, vv in r.items() if kk != "content"}
                        for r in v[:3]
                    ]
                elif k == "infoboxes":
                    debug_data[k] = v[:2]
                else:
                    debug_data[k] = v
            print(f"\n  原始响应:\n{json.dumps(debug_data, ensure_ascii=False, indent=2)[:2000]}")

        return raw_result

    except Exception as exc:
        elapsed_ms = int((time.time() - start_ts) * 1000)
        return {
            "label": label,
            "status_code": 0,
            "elapsed_ms": elapsed_ms,
            "query": query,
            "categories": categories,
            "time_range": time_range,
            "pageno": pageno,
            "result_count": 0,
            "infobox_count": 0,
            "error": str(exc),
            "unresponsive_engines": [],
            "engine_result_count": {},
        }


def print_result(result: dict[str, Any]) -> None:
    """友好打印单次搜索结果"""
    status_str = "[OK]" if result["result_count"] > 0 else "[FAIL]"
    print(f"\n{status_str} [{result['label']}]")
    print(f"  查询词:      {result['query']}")
    print(f"  分类:        {result['categories']}")
    print(f"  时间范围:    {result['time_range']}")
    print(f"  页码:        {result['pageno']}")
    print(f"  状态码:      {result['status_code']}")
    print(f"  耗时:        {result['elapsed_ms']}ms")

    if "error" in result:
        print(f"  [错误] {result['error']}")
        return

    print(f"  结果数:      {result['result_count']}")
    print(f"  信息框数:    {result['infobox_count']}")
    print(f"  建议词数:    {result['suggestion_count']}")
    print(f"  答案数:      {result['answer_count']}")

    if result.get("unresponsive_engines"):
        print(f"  无响应引擎:  {result['unresponsive_engines']}")

    if result.get("engine_result_count"):
        print(f"  引擎结果统计: {result['engine_result_count']}")

    if result["suggestions"]:
        print(f"  建议词:      {', '.join(result['suggestions'])}")

    if result["answers"]:
        for a in result["answers"]:
            print(f"  答案:        {a}")

    if result["all_titles"]:
        print(f"  结果标题:")
        for i, title in enumerate(result["all_titles"], 1):
            print(f"    {i}. {title}")
    else:
        print(f"  结果标题:    (无)")


async def run_diagnostics() -> None:
    """
    执行多轮诊断搜索。
    """
    print("=" * 60)
    print("[SearXNG 搜索诊断脚本]")
    print(f"  实例地址: {BASE_URL}")
    print(f"  当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # ============================================================
        # 第〇步：检查 SearXNG 实例健康状态
        # ============================================================
        await check_searxng_health(client)

        # ============================================================
        # 第一步：精确复现日志中的请求（带原始响应打印）
        # ============================================================
        print_sep("第一步：精确复现日志请求参数 + 原始响应")

        result_1 = await single_search_debug(
            client, "复现-中文", "2026年6月14日 世界杯 比赛结果",
            "general,news", "day", show_raw=True,
        )
        print_result(result_1)

        # ============================================================
        # 第二步：测试不同参数组合
        # ============================================================
        test_cases = [
            # (label, query, categories, time_range)
            ("无参数-空字符串", "", "", ""),
            ("纯英文-test", "test", "", ""),
            ("纯中文-你好", "你好", "", ""),
            ("纯数字-2026", "2026", "", ""),
            ("常见词-weather", "weather", "", ""),
            ("常见词-news today", "news today", "", ""),
            ("英文-World Cup", "World Cup 2026", "", ""),
            ("中文-世界杯", "世界杯", "", ""),
        ]

        print_sep("第二步：测试不同参数组合（含空查询、常见词）")
        all_results = []
        for label, q, cat, tr in test_cases:
            r = await single_search_debug(client, label, q, cat, tr)
            print_result(r)
            all_results.append(r)

        # ============================================================
        # 第三步：不传 categories 参数 vs 传空 categories
        # ============================================================
        print_sep("第三步：categories 参数影响测试")

        # 测试不带 categories 参数（完全移除）
        for q in ["test", "news", "世界杯"]:
            url = f"{BASE_URL}/search"
            params = {"format": "json", "safesearch": 0, "q": q, "pageno": 1}
            try:
                resp = await client.get(
                    url, params=params,
                    headers={"User-Agent": "Luna-AI/1.0 (Diagnostic)", "Accept": "application/json"},
                )
                data = resp.json()
                results = data.get("results", [])
                engines_info = data.get("engines", [])
                unresponsive = data.get("unresponsive_engines", [])
                print(f"\n  [无categories] q={q!r} => results={len(results)}, engines={engines_info[:3]}, unresponsive={unresponsive}")
                if results:
                    print(f"    第一条: {results[0].get('title', '')} - {results[0].get('url', '')}")
            except Exception as e:
                print(f"  [错误] q={q!r}: {e}")

        # ============================================================
        # 结论汇总
        # ============================================================
        print_sep("诊断结论汇总")

        total = len(all_results)
        with_results = sum(1 for r in all_results if r["result_count"] > 0)
        without_results = total - with_results

        print(f"  总测试次数: {total}")
        print(f"  有结果:     {with_results}")
        print(f"  无结果:     {without_results}")

        if without_results == total:
            print("\n  [严重] 所有搜索均无结果！根因分析：")
            print("     1. SearXNG 实例可达（HTTP 200），但所有引擎返回 0 结果")
            print("     2. 可能原因：")
            print("        a) searxng.yml 中未启用任何搜索引擎（所有引擎 disabled）")
            print("        b) 启用的引擎全部不可用（如需要 API Key 但未配置）")
            print("        c) 启用的引擎只支持特定语言/地区查询")
            print("     3. 解决方案：登录 SearXNG Web UI 管理页面检查引擎状态")
            print(f"        - 访问 {BASE_URL}/config 查看当前配置")
            print(f"        - 检查 {BASE_URL}/stats 查看引擎统计")
            print("        - 确认 searxng.yml 中至少启用了 google, bing, duckduckgo 等通用引擎")
        else:
            print(f"\n  部分搜索成功，有 {with_results}/{total} 次返回了结果。")
            success = [r for r in all_results if r["result_count"] > 0]
            print("\n  [成功] 参数组合:")
            for r in success[:10]:
                print(f"    - query={r['query']!r} categories={r['categories']!r} => {r['result_count']} 条结果")


def main() -> None:
    asyncio.run(run_diagnostics())


if __name__ == "__main__":
    main()
