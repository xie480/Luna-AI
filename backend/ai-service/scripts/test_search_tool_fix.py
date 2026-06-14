import asyncio
import os
import sys

# 将 backend 目录添加到 sys.path 以便导入 app 模块
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from app.skills.web_search.search_tool import handle_searxng_search
from app.config.tool_config_manager import ToolConfigManager

async def test_search():
    # 模拟前端配置
    config_mgr = ToolConfigManager()
    config_mgr.reload_single("web_search", {
        "base_url": "http://192.168.100.128:8888",
        "results_per_request": 5,
        "timeout": 15.0
    })

    with open("backend/ai-service/scripts/search_output.txt", "w", encoding="utf-8") as f:
        f.write("开始测试 `handle_searxng_search`...\n\n")
        
        # 测试 1: 模拟大模型请求 (不带 categories)
        f.write("--- 测试 1: 不带 categories (让 SearXNG 决定) ---\n")
        parameters_1 = {
            "query": [
                ["2026年6月14日 世界杯 比赛结果"],
                ["FIFA World Cup 2026 June 14 results"],
                ["2026世界杯 6月14日 战报"]
            ]
        }
        result_1 = await handle_searxng_search(parameters_1, "test-trace-1")
        f.write(result_1 + "\n\n")
        
if __name__ == "__main__":
    asyncio.run(test_search())
