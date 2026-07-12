import asyncio
import httpx
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import os
from dotenv import load_dotenv

async def test():
    load_dotenv()
    token = os.environ.get("SMITHERY_SERVICE_TOKEN", "") 
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    urls_to_try = [
        "https://mcp.smithery.run/sse/yilena05050",
        "https://mcp.smithery.run/sse",
        "https://mcp.smithery.run/yilena05050/sse",
        "https://server.smithery.ai/youtube/sse",
        "https://server.smithery.ai/sse/youtube",
        "https://server.smithery.ai/youtube",
        "https://api.smithery.ai/connect/yilena05050/youtube/sse",
        "https://api.smithery.ai/connect/yilena05050/sse/youtube"
    ]
    
    for url in urls_to_try:
        print(f"\nTrying to connect to SSE at: {url}")
        try:
            from contextlib import AsyncExitStack
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(url=url, headers=headers, timeout=10.0)
                )
                print(f"SUCCESS: Connected to {url}")
                return
        except Exception as e:
            print(f"Failed")

if __name__ == "__main__":
    asyncio.run(test())
