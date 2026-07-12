import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import traceback
import os
from dotenv import load_dotenv

async def test():
    load_dotenv()
    url = "https://mcp.smithery.run/yilena05050"
    token = os.environ.get("SMITHERY_SERVICE_TOKEN", "") 
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    
    print(f"Trying to connect to SSE at: {url}")
    
    try:
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(url=url, headers=headers, timeout=30.0)
            )
            session = ClientSession(read_stream, write_stream)
            await stack.enter_async_context(session)
            print("SSE stream established. Initializing session...")
            
            await asyncio.wait_for(session.initialize(), timeout=30.0)
            print("Session initialized successfully!")
            
            tools_res = await session.list_tools()
            print("\nTools via MCP SDK:")
            for tool in tools_res.tools:
                print(f" - {tool.name}")
                
            print("\nCalling tool...")
            res = await session.call_tool("youtube_search", {"q": "cats", "maxResults": 2, "type": "video"})
            print(f"Result: {res}")
                
    except Exception as e:
         print(f"Error during SSE connection/initialization: {e}")
         traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
