"""
MCP 市场数据诊断脚本（独立版）。

直接请求官方 Registry API 并查询 PostgreSQL。
"""
import asyncio
import httpx
import json
import os


async def diagnose_registry():
    print("=" * 60)
    print("1. 直接请求官方 Registry API")
    print("=" * 60)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://registry.modelcontextprotocol.io/v0.1/servers",
                headers={"Accept": "application/json"},
            )
            print(f"状态码: {response.status_code}")
            data = response.json()

            # 解析顶层结构
            if isinstance(data, list):
                print(f"顶层: list, 长度={len(data)}")
                server_list = data
            elif isinstance(data, dict):
                print(f"顶层: dict, 键={list(data.keys())}")
                server_list = data.get("servers", data.get("data", []))
            else:
                server_list = []

            print(f"总条目数: {len(server_list)}")

            # 查看前 2 个条目的完整结构
            for i, entry in enumerate(server_list[:2]):
                print(f"\n{'=' * 40}")
                print(f"条目 {i+1}")
                print(f"{'=' * 40}")

                if not isinstance(entry, dict):
                    print(f"类型: {type(entry)}")
                    continue

                svr = entry.get("server", entry)
                print(f"顶层键: {list(entry.keys())}")
                print(f"server 类型: {type(svr).__name__}")
                print(f"server 键: {list(svr.keys())}")

                # 关键：检查 capabilities
                if "capabilities" in svr:
                    caps = svr["capabilities"]
                    print(f"\n>>> capabilities 存在!")
                    print(f"capabilities 键: {list(caps.keys())}")
                    tools = caps.get("tools", [])
                    print(f"tools 数量: {len(tools)}")
                    if tools:
                        print(f"第一个 tool 结构:\n{json.dumps(tools[0], indent=2, ensure_ascii=False)[:600]}")
                    else:
                        print("tools 为空列表")

                    # 检查顶层有没有 tools 字段
                    if "tools" in svr:
                        print(f"\n>>> server 顶层也有 tools 字段!")
                        print(f"顶层 tools 数量: {len(svr['tools'])}")
                else:
                    print(f"\n>>> capabilities 字段不存在!")
                    # 打印所有字段看看
                    for k, v in svr.items():
                        vtype = type(v).__name__
                        if isinstance(v, (dict, list)):
                            vpreview = json.dumps(v, ensure_ascii=False)[:150]
                        else:
                            vpreview = str(v)[:150]
                        print(f"  {k}: {vtype} = {vpreview}")

    except Exception as e:
        print(f"注册表 API 失败: {e}")
        import traceback
        traceback.print_exc()


# === 查询数据库（使用环境变量连接 PG） ===
async def diagnose_db():
    print("\n" + "=" * 60)
    print("2. 查询 PostgreSQL 中的 mcp_marketplace 表数据")
    print("=" * 60)

    # 尝试从 .env 或环境变量读取 PG 连接参数
    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_db = os.environ.get("POSTGRES_DB", "luna_ai")
    pg_user = os.environ.get("POSTGRES_USER", "luna")
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "luna_secret")

    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=pg_host,
            port=int(pg_port),
            database=pg_db,
            user=pg_user,
            password=pg_pass,
        )

        # 查询前 2 条记录的 capabilities 列
        rows = await conn.fetch(
            "SELECT id, name, display_name, capabilities, health_detail, security_flags, original_data "
            "FROM mcp_marketplace LIMIT 2"
        )

        if not rows:
            print("数据库中无数据")
            await conn.close()
            return

        for row in rows:
            print(f"\n--- {row['name']} (id={row['id'][:16]}...) ---")
            
            caps = row['capabilities']
            print(f"capabilities: {json.dumps(caps, ensure_ascii=False)[:400]}")
            
            hd = row['health_detail']
            print(f"health_detail: {json.dumps(hd, ensure_ascii=False)[:200]}")
            
            sf = row['security_flags']
            print(f"security_flags: {json.dumps(sf, ensure_ascii=False)[:200]}")

            # 如果 capabilities 为空，检查 original_data
            if not caps or not caps.get("tools"):
                print(f"\n  [诊断] capabilities 为空，检查 original_data...")
                od = row['original_data'] or {}
                print(f"  original_data 顶层键: {list(od.keys())[:10]}")
                server_data = od.get("server", {})
                if server_data and isinstance(server_data, dict):
                    print(f"  original_data.server 键: {list(server_data.keys())[:15]}")
                    if "capabilities" in server_data:
                        print(f"  >>> original_data.server.capabilities 存在!")
                        server_caps = server_data["capabilities"]
                        if isinstance(server_caps, dict):
                            print(f"      类型: {type(server_caps).__name__}")
                            print(f"      键: {list(server_caps.keys())[:10]}")
                            print(f"      预览: {json.dumps(server_caps, ensure_ascii=False)[:400]}")
                        else:
                            print(f"      值: {str(server_caps)[:200]}")
                    else:
                        print(f"  >>> original_data.server 中也没有 capabilities")
                        # 查看 server 里有些什么
                        for k in list(server_data.keys())[:8]:
                            v = server_data[k]
                            vtype = type(v).__name__
                            vpreview = json.dumps(v, ensure_ascii=False)[:100] if isinstance(v, (dict, list)) else str(v)[:100]
                            print(f"    {k}: {vtype} = {vpreview}")
                else:
                    print(f"  original_data 中没有 server 字段, keys={list(od.keys())[:5]}")

        await conn.close()

    except ImportError:
        print("asyncpg 未安装，尝试 raw sqlalchemy...")
        try:
            from sqlalchemy import create_engine, text
            dsn = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
            engine = create_engine(dsn)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id, name, display_name, capabilities, health_detail, security_flags, original_data FROM mcp_marketplace LIMIT 2")
                ).fetchall()
                for row in rows:
                    print(f"\n--- {row[1]} ---")
                    print(f"capabilities: {json.dumps(row[3], ensure_ascii=False)[:400]}")
                    print(f"health_detail: {json.dumps(row[4], ensure_ascii=False)[:200]}")
                    print(f"security_flags: {json.dumps(row[5], ensure_ascii=False)[:200]}")
                    od = row[6] or {}
                    print(f"original_data 键: {list(od.keys())[:5]}")
                    if "server" in od:
                        print(f"server 键: {list(od['server'].keys())[:10]}")
                        if "capabilities" in od["server"]:
                            print(f">>> original_data.server.capabilities 存在!")
                            print(f"预览: {json.dumps(od['server']['capabilities'], ensure_ascii=False)[:400]}")
            engine.dispose()
        except Exception as e2:
            print(f"数据库查询也失败: {e2}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"数据库查询失败: {e}")
        import traceback
        traceback.print_exc()


async def main():
    await diagnose_registry()
    await diagnose_db()


if __name__ == "__main__":
    asyncio.run(main())
