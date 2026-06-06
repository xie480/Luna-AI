import asyncio
from app.infrastructure.redis import RedisClient

async def main():
    client = RedisClient('192.168.100.128:6379', db=2)
    redis_client = client.get_client()
    
    keys = []
    async for key in redis_client.scan_iter(match="luna:mem:chat:*:history"):
        keys.append(key)
    print("scan_iter history keys:", keys)

if __name__ == "__main__":
    asyncio.run(main())
