import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import json

async def test():
    namespace = "yilena05050"
    base_url = "https://api.smithery.ai"
    token = "sm_4oV9G7Q34vX9rGk9Wd8vL"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    print(f"Connecting to namespace: {namespace}...")
    
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        # 1. Fetch servers to get server connection details
        servers_url = f"{base_url}/connect/{namespace}"
        resp = await client.get(servers_url)
        data = resp.json()
        connections = data.get("connections", [])
        
        youtube_conn = next((c for c in connections if c["connectionId"] == "youtube"), None)
        if not youtube_conn:
            print("Youtube connection not found.")
            return
            
        print(f"Youtube Server details:")
        print(json.dumps(youtube_conn, indent=2))
        
        # In smithery, the actual SSE URL for a server is usually base_url/connect/{namespace}/{server_id}
        sse_url = f"{base_url}/connect/{namespace}/youtube"
        print(f"\nTrying to connect to SSE at: {sse_url}")
        
        try:
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(url=sse_url, headers=headers, timeout=30.0)
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
             import traceback
             print(f"Error during SSE connection/initialization: {e}")
             traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
