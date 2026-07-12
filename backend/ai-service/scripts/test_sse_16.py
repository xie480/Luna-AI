import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import traceback
import os
from dotenv import load_dotenv

async def test():
    load_dotenv()
    token = os.environ.get("SMITHERY_SERVICE_TOKEN", "") 
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    
    namespace = "yilena05050"
    base_url = "https://api.smithery.ai"
    
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        servers_url = f"{base_url}/connect/{namespace}"
        resp = await client.get(servers_url)
        data = resp.json()
        connections = data.get("connections", [])
        
        target_conn = next((c for c in connections if "youtube" in c.get("name", "").lower()), None)
        if not target_conn:
            print("Target connection not found.")
            return
            
        # The key is to use mcpUrl for SSE connection
        mcp_url = target_conn.get("mcpUrl")
        print(f"\nTrying to connect to SSE at: {mcp_url}")
        
        try:
            from contextlib import AsyncExitStack
            from httpx_sse import connect_sse
            
            # Use httpx_sse to see actual response
            print("Making normal HTTP request first...")
            resp = await client.get(mcp_url)
            print(f"Status: {resp.status_code}")
            print(f"Headers: {resp.headers}")
            print(f"Body snippet: {resp.text[:200]}")
            
        except Exception as e:
             print(f"Error during SSE connection/initialization: {e}")
             traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
