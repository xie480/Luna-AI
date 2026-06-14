"""
SearXNG 引擎配置检查脚本

做什么：获取 SearXNG 实例的 /config JSON（含引擎列表和启用状态）。
"""

import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import json

import httpx

BASE_URL = "http://192.168.100.128:8888"


async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 获取完整 config
        resp = await client.get(
            f"{BASE_URL}/config",
            headers={"User-Agent": "Luna-AI/1.0 (Diagnostic)"},
        )
        config = resp.json()

        # 打印引擎列表（只保留关键字段）
        engines = config.get("engines", [])
        print(f"引擎总数: {len(engines)}")
        print()
        print(f"{'引擎名称':<25} {'启用':<10} {'分类':<30} {'语言支持':<12}")
        print("-" * 80)
        
        enabled_count = 0
        disabled_count = 0
        for eng in engines:
            name = eng.get("name", "?")
            enabled = eng.get("enabled", False)
            cats = ",".join(eng.get("categories", []))
            lang_support = eng.get("language_support", False)
            status = "是" if enabled else "否"
            if enabled:
                enabled_count += 1
            else:
                disabled_count += 1
            print(f"{name:<25} {status:<10} {cats:<30} {str(lang_support):<12}")
        
        print()
        print(f"已启用: {enabled_count}")
        print(f"已禁用: {disabled_count}")
        
        # 如果有已启用的引擎，检查是否所有启用的都在 timeout
        if enabled_count > 0:
            print(f"\n已启用的引擎名称: {[e['name'] for e in engines if e.get('enabled')]}")
        
        # 查看 categories 列表
        print(f"\n可用分类: {config.get('categories', [])}")
        
        # 查看 default_locale
        print(f"\n默认区域: {config.get('default_locale', '未设置')!r}")
        
        # 检查是否有 token 限制
        print(f"\n实例信息:")
        print(f"  版本: {config.get('brand', {}).get('GIT_BRANCH', '?')}")
        print(f"  主题: {config.get('default_theme', '?')}")


asyncio.run(main())
