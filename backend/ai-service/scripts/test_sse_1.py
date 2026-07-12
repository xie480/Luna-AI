import asyncio
from mcp.client.sse import sse_client

async def test():
    url = "https://api.smithery.ai/connect/yilena05050/youtube"
    headers = {"Authorization": "Bearer sm_4oV9G7Q34vX9rGk9Wd8vL"} 
    print("Testing api.smithery.ai SSE...")
    try:
        async with sse_client(url=url, headers=headers, timeout=10) as (read, write):
            print("Connected to api.smithery.ai via SSE!")
    except Exception as e:
        print(f"Error api.smithery.ai: {e}")

if __name__ == "__main__":
    asyncio.run(test())
