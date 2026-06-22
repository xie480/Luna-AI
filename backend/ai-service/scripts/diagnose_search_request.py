"""
诊断脚本：测试 SearXNG 搜索请求，定位搜索无结果的原因。

做什么：使用少量关键测试，每次请求间隔 15 秒避免触发引擎限流。
        对比有无 language 参数、不同引擎组合的效果。
使用方法：
    cd backend/ai-service
    python scripts/diagnose_search_request.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE_URL = "http://192.168.100.128:8888"
TIMEOUT = 30.0
# 每次请求间隔，避免触发 SearXNG 引擎限流
REQUEST_INTERVAL = 15.0

results_log: list[dict] = []


async def run_test(test_id: int, label: str, params: dict, headers: dict | None = None) -> dict:
    """执行单个测试并记录结果。"""
    if headers is None:
        headers = {"Accept": "application/json"}

    print(f"\n[测试 {test_id:02d}] {label}")
    print(f"  参数: {json.dumps(params, ensure_ascii=False)}")

    entry: dict = {
        "id": test_id,
        "label": label,
        "params": json.dumps(params, ensure_ascii=False),
        "results_count": 0,
        "available_engines": [],
        "unresponsive_engines": [],
        "status": "",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{BASE_URL}/search", params=params, headers=headers)

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    entry["status"] = "JSON解析失败"
                    print(f"  结果: JSON 解析失败")
                    results_log.append(entry)
                    return entry

                results_count = len(data.get("results", []))
                unresponsive = data.get("unresponsive_engines", [])

                available = []
                for r in data.get("results", []):
                    eng = r.get("engine", "")
                    if eng and eng not in available:
                        available.append(eng)

                entry["results_count"] = results_count
                entry["available_engines"] = available
                entry["unresponsive_engines"] = [f"{name}: {reason}" for name, reason in unresponsive]
                entry["status"] = "成功" if results_count > 0 else "空结果"

                print(f"  结果数: {results_count}")
                print(f"  可用引擎: {', '.join(available) if available else '无'}")
                if unresponsive:
                    print(f"  不可用引擎:")
                    for name, reason in unresponsive:
                        print(f"    - {name}: {reason}")

                if results_count > 0:
                    print(f"  前 3 条:")
                    for i, r in enumerate(data["results"][:3], 1):
                        t = r.get("title", "N/A")[:80]
                        e = r.get("engine", "?")
                        u = r.get("url", "")[:80]
                        print(f"    {i}. [{e}] {t}")
                        print(f"       {u}")
            else:
                entry["status"] = f"HTTP {response.status_code}"
                print(f"  结果: HTTP {response.status_code}")
                if response.status_code == 400:
                    print(f"  提示: SearXNG 不接受空字符串参数（如 language=''）")

    except Exception as e:
        entry["status"] = f"异常: {type(e).__name__}"
        print(f"  结果: 异常 {type(e).__name__}: {e}")

    results_log.append(entry)
    return entry


async def main():
    print("=" * 90)
    print("SearXNG 诊断（改进版：请求间隔 15s，避免触发引擎限流）")
    print(f"SearXNG 地址: {BASE_URL}")
    print(f"超时时间: {TIMEOUT}s | 请求间隔: {REQUEST_INTERVAL}s")
    print("=" * 90)

    test_id = 0

    # ============================================================
    # 测试 1: 基线 — 最简英文查询
    # ============================================================
    test_id += 1
    await run_test(test_id, "基线: q=test（最简参数）", {"q": "test", "format": "json"})

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 2: 中文查询，无 language（模拟修复前代码行为）
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "中文查询 无 language（修复前行为）",
        {"q": "2022世界杯 冷门", "format": "json", "safesearch": 0, "pageno": 1},
    )

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 3: 中文查询 + language=zh-CN（修复后行为）
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "中文查询 + language=zh-CN（修复后行为）",
        {"q": "2022世界杯 冷门", "format": "json", "language": "zh-CN", "safesearch": 0, "pageno": 1},
    )

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 4: 英文查询，无 language
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "英文查询 无 language",
        {"q": "2022 World Cup upsets", "format": "json", "safesearch": 0, "pageno": 1},
    )

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 5: 英文查询 + language=en
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "英文查询 + language=en",
        {"q": "2022 World Cup upsets", "format": "json", "language": "en", "safesearch": 0, "pageno": 1},
    )

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 6: 中文查询 + engines=brave,bing
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "中文查询 + language=zh-CN + engines=brave,bing",
        {"q": "2022世界杯 冷门", "format": "json", "language": "zh-CN", "engines": "brave,bing"},
    )

    await asyncio.sleep(REQUEST_INTERVAL)

    # ============================================================
    # 测试 7: 中文查询 + categories=news
    # ============================================================
    test_id += 1
    await run_test(
        test_id,
        "中文查询 + language=zh-CN + categories=news",
        {"q": "2022世界杯 冷门", "format": "json", "language": "zh-CN", "categories": "news"},
    )

    # ============================================================
    # 汇总报告
    # ============================================================
    print("\n\n" + "=" * 110)
    print("汇总报告")
    print("=" * 110)
    print(f"{'ID':>3} | {'结果数':>6} | {'状态':<10} | {'可用引擎':<20} | {'不可用':>5} | {'标签'}")
    print("-" * 110)
    for r in results_log:
        avail = ", ".join(r["available_engines"][:3]) if r["available_engines"] else "-"
        unresp = len(r["unresponsive_engines"])
        print(f"{r['id']:>3} | {r['results_count']:>6} | {r['status']:<10} | {avail:<20} | {unresp:>5} | {r['label']}")

    # ============================================================
    # 结论
    # ============================================================
    print("\n" + "=" * 110)
    print("结论分析")
    print("=" * 110)

    # 引擎状态汇总
    all_engines: dict[str, list[str]] = {}
    for r in results_log:
        for ue in r["unresponsive_engines"]:
            parts = ue.split(": ", 1)
            eng = parts[0]
            reason = parts[1] if len(parts) > 1 else "unknown"
            if eng not in all_engines:
                all_engines[eng] = []
            if reason not in all_engines[eng]:
                all_engines[eng].append(reason)

    if all_engines:
        print("\n引擎状态汇总:")
        for eng, reasons in sorted(all_engines.items()):
            print(f"  {eng}: {'; '.join(reasons)}")

    # 修复前后对比
    before = [r for r in results_log if "修复前" in r["label"]]
    after = [r for r in results_log if "修复后" in r["label"]]
    if before and after:
        print(f"\n修复前后对比:")
        print(f"  修复前（无 language）: 结果数={before[0]['results_count']}")
        print(f"  修复后（language=zh-CN）: 结果数={after[0]['results_count']}")

    # 最终判断
    all_zero = all(r["results_count"] == 0 for r in results_log)
    if all_zero:
        print("\n⚠️ 所有测试均返回 0 结果。SearXNG 所有引擎不可用，需要在 SearXNG 服务器端排查。")
    else:
        has_lang_effect = False
        for r in results_log:
            if r["results_count"] > 0:
                has_lang_effect = True
                print(f"\n✅ 测试 {r['id']} 返回了 {r['results_count']} 条结果: {r['label']}")
        if not has_lang_effect:
            print("\n⚠️ 无任何有效结果，请检查 SearXNG 引擎配置。")


if __name__ == "__main__":
    print("开始诊断...")
    asyncio.run(main())
    print("\n诊断完成。")
