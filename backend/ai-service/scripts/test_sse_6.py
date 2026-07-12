import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import traceback

async def test():
    namespace = "yilena05050"
    base_url = "https://api.smithery.ai"
    token = "sm_4oV9G7Q34vX9rGk9Wd8vL"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    print(f"Connecting to namespace: {namespace}...")
    
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        servers_url = f"{base_url}/connect/{namespace}"
        resp = await client.get(servers_url)
        data = resp.json()
        connections = data.get("connections", [])
        
        target_conn = next((c for c in connections if "youtube" in c.get("connectionId", "").lower()), None)
        if not target_conn:
            print("Target connection not found.")
            return
            
        mcp_url = target_conn.get("mcpUrl")
        print(f"\nTrying to connect to SSE at: {mcp_url}")
        
        try:
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(url=mcp_url, headers=headers, timeout=30.0)
                )
                session = ClientSession(read_stream, write_stream)
                await stack.enter_async_context(session)
                print("SSE stream established. Initializing session...")
                
                await session.initialize()
                print("Session initialized successfully!")
                
                # Fetch tools
                tools_res = await session.list_tools()
                print("\nTools via MCP SDK:")
                for tool in tools_res.tools:
                    print(f" - {tool.name}")
                    
        except Exception as e:
             print(f"Error during SSE connection/initialization: {e}")
             traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
