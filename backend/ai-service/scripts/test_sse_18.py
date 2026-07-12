import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import traceback
import os
from dotenv import load_dotenv
import json

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
            
        server_id = target_conn.get("connectionId")
        
        # Test callTool endpoint
        tool_url = f"{base_url}/connect/{namespace}/{server_id}/.tools/search_you_tube"
        print(f"\nTrying to call tool REST at: {tool_url}")
        
        payload = {
            "q": "cats",
            "type": "video",
            "maxResults": 2
        }
        try:
            print("Making normal HTTP request first to see if it's SSE...")
            resp = await client.post(tool_url, json=payload)
            print(f"Status: {resp.status_code}")
            print(f"Headers: {resp.headers}")
            print(f"Body snippet: {resp.text[:200]}")
            
        except Exception as e:
             print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())
