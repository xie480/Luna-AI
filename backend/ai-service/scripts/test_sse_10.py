import asyncio
import httpx

async def test():
    namespace = "yilena05050"
    base_url = "https://api.smithery.ai"
    token = "sm_4oV9G7Q34vX9rGk9Wd8vL"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    print(f"Connecting to namespace: {namespace}...")
    
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        servers_url = f"{base_url}/connect/{namespace}"
        resp = await client.get(servers_url)
        print(resp.status_code)
        print(resp.text)

if __name__ == "__main__":
    asyncio.run(test())
