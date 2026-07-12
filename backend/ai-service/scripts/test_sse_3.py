import asyncio
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async def test():
    url = "https://mcp.smithery.run/yilena05050"
    headers = {"Authorization": "Bearer sm_4oV9G7Q34vX9rGk9Wd8vL"} 
    print("Testing mcp.smithery.run SSE...")
    try:
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(
                sse_client(url=url, headers=headers, timeout=10)
            )
            print("Connected to mcp.smithery.run via SSE!")
            session = ClientSession(read, write)
            await stack.enter_async_context(session)
            await session.initialize()
            print("Session initialized!")
            
            # Fetch tools
            tools = await session.list_tools()
            print(f"Tools: {[t.name for t in tools.tools]}")
            
    except Exception as e:
        print(f"Error mcp.smithery.run: {e}")

if __name__ == "__main__":
    asyncio.run(test())
