import asyncio
import httpx
import json
import os
from dotenv import load_load

async def test_smithery_discovery():
    base_url = "https://api.smithery.ai"
    
    # smithery 的 public registry API，不需要 token
    registry_url = f"https://api.smithery.ai/v1/registry/packages"
    print(f"Testing Smithery Registry API...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # 先找一个可用的包
            print(f"\n1. Fetching packages from {registry_url}...")
            reg_resp = await client.get(registry_url)
            print(f"Registry Status Code: {reg_resp.status_code}")
            
            if reg_resp.status_code == 200:
                data = reg_resp.json()
                packages = data.get("data", [])
                
                if not packages:
                    print("No packages found.")
                    return
                
                # 取第一个包作为测试目标
                test_pkg = packages[0]
                pkg_name = test_pkg.get("name")
                print(f"Using test package: {pkg_name}")
                
                # 对于工具结构，我们不需要真实的 auth token 来连接 SSE
                # 我们直接看获取 tools 的接口
                # 有些开源 server 会在 smithery 暴露 public api 获取 manifest
                # 或者我们可以直接参考 discovery_sync 里的逻辑，使用项目中配置好的 token
                
                print("\nSince connect API requires token, we will simulate the tools response based on standard MCP tools schema...")
                
                print("\n=== EXPECTED TOOLS SCHEMA ===")
                print("""
The typical tools response from an MCP server follows this JSON-RPC schema:

{
  "tools": [
    {
      "name": "tool_name",
      "description": "A description of what the tool does.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "param1": {
            "type": "string",
            "description": "Description of param1"
          }
        },
        "required": ["param1"]
      }
    }
  ]
}
""")
                
            else:
                print(f"Failed to fetch registry: {reg_resp.text}")
                
        except Exception as e:
            print(f"Error: {e}")
            print(f"Status Code: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                connections = data.get("connections", [])
                
                if not connections:
                    print("No connections found for this namespace.")
                    return
                
                # 取第一个 connection
                conn = connections[0]
                server_id = conn["connectionId"]
                print(f"\nFound Server ID: {server_id}")
                
                # 获取 tools (模拟 discovery_sync 中的步骤3)
                tools_url = f"{base_url}/connect/@{test_namespace}/{server_id}/.tools"
                print(f"\n2. Fetching tools from {tools_url}...")
                
                tools_resp = await client.get(tools_url)
                print(f"Status Code: {tools_resp.status_code}")
                
                if tools_resp.status_code == 200:
                    tools_data = tools_resp.json()
                    print("\n=== RAW TOOLS RESPONSE ===")
                    print(json.dumps(tools_data, indent=2, ensure_ascii=False))
                else:
                    print(f"Failed to fetch tools: {tools_resp.text}")
            else:
                print(f"Failed to fetch connections: {resp.text}")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_smithery_discovery())
