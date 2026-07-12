import asyncio
import httpx
import json

async def test():
    namespace = "yilena05050"
    server_id = "youtube"
    tool_name = "search_you_tube"
    base_url = "https://api.smithery.ai"
    token = "sm_4oV9G7Q34vX9rGk9Wd8vL"
    
    url = f"{base_url}/connect/{namespace}/{server_id}/.tools/{tool_name}"
    headers = {
        "Accept": "application/json", 
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "q": "cats",
        "type": "video",
        "maxResults": 2
    }
    print(f"POST {url}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        print(f"Status: {resp.status_code}")
        try:
            print(json.dumps(resp.json(), indent=2))
        except:
            print(resp.text)

if __name__ == "__main__":
    asyncio.run(test())
