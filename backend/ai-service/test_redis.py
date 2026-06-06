import asyncio
from app.infrastructure.redis import RedisClient
from app.repository.chat_history_redis import ChatHistoryRedisRepo

async def main():
    client = RedisClient('127.0.0.1:6379')
    repo = ChatHistoryRedisRepo(client)
    
    redis_client = client.get_client()
    keys = await redis_client.keys("luna:mem:chat:*")
    print("All chat keys:", keys)
    
    ids = await repo.get_all_session_ids()
    print("Session IDs from repo:", ids)
    
    for sid in ids:
        summary, history = await repo.get_context(sid)
        print(f"Session {sid}: history length = {len(history)}")

if __name__ == "__main__":
    asyncio.run(main())
