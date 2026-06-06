import asyncio
from app.infrastructure.postgres import PostgresClient
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo

async def main():
    client = PostgresClient('postgresql+asyncpg://yilena:XUWENBO219382@192.168.100.128:5432/luna_ai')
    
    async with client.session_factory() as session:
        from sqlalchemy import text
        res = await session.execute(text('SELECT DISTINCT session_id FROM interactions'))
        interaction_sessions = res.scalars().all()
        print('Session IDs in interactions:', interaction_sessions)
        
        res2 = await session.execute(text('SELECT DISTINCT session_id FROM long_term_memories WHERE status = \'ACTIVE\''))
        ltm_sessions = res2.scalars().all()
        print('Session IDs in long_term_memories:', ltm_sessions)

if __name__ == "__main__":
    asyncio.run(main())
