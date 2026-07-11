import asyncio
import os
import httpx
from dotenv import load_dotenv

async def main():
    # 强制从 .env 加载
    load_dotenv()
    
    namespace = os.environ.get("SMITHERY_NAMESPACE", "yilena05050")
    api_key = os.environ.get("SMITHERY_SERVICE_TOKEN", "") 
    base_url = "https://api.smithery.ai"
    
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    print(f"Connecting to namespace: {namespace}...")
    
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            url = f"{base_url}/connect/{namespace}"
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            
            connections = data.get("connections", [])
            print(f"Found {len(connections)} connections.")
            
            for i, conn in enumerate(connections):
                print(f"\n--- Connection {i+1} ---")
                for k, v in conn.items():
                    print(f"{k}: {v}")
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
