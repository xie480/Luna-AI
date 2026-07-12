import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import traceback
import os
from dotenv import load_dotenv

async def test():
    load_dotenv()
    namespace = os.environ.get("SMITHERY_NAMESPACE", "yilena05050")
    base_url = "https://api.smithery.ai"
    token = os.environ.get("SMITHERY_SERVICE_TOKEN", "") 
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
        
        # When connecting to the remote server itself, the authorization header is required
        # Some remote servers might be using a different auth schema or require the actual 
        # mcp url we got from the initial connection. 
        # But wait! Smithery handles the proxy! We don't connect to server.smithery.ai/youtube directly with our token!
        # The correct way to use Smithery public registry through the proxy is to use 
        # api.smithery.ai/connect/{namespace}/{server_id}
        
        correct_sse_url = f"{base_url}/connect/{namespace}/youtube"
        print(f"Trying to connect to correct Smithery proxy SSE at: {correct_sse_url}")
        
        try:
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(url=correct_sse_url, headers={"Authorization": f"Bearer {token}"}, timeout=60.0)
                )
                session = ClientSession(read_stream, write_stream)
                await stack.enter_async_context(session)
                print("SSE stream established. Initializing session...")
                
                # Initialize with timeout
                await asyncio.wait_for(session.initialize(), timeout=30.0)
                print("Session initialized successfully!")
                
                # Fetch tools
                tools_res = await session.list_tools()
                print("\nTools via MCP SDK:")
                for tool in tools_res.tools:
                    print(f" - {tool.name}")
                    
                # Call tool
                print("\nCalling tool...")
                res = await session.call_tool("search_you_tube", {"q": "cats", "maxResults": 2, "type": "video"})
                print(f"Result: {res}")
                    
        except Exception as e:
             print(f"Error during SSE connection/initialization: {e}")
             traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
