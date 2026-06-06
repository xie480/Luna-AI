import asyncio
from datetime import datetime
from app.infrastructure.postgres import PostgresClient
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.models import InteractionModel
from sqlalchemy import select

async def main():
    client = PostgresClient('postgresql+asyncpg://yilena:XUWENBO219382@192.168.100.128:5432/luna_ai')
    
    async with client.session_factory() as session:
        stmt = select(InteractionModel.session_id).distinct()
        result = await session.execute(stmt)
        all_interaction_sessions = result.scalars().all()
        print('all_interaction_sessions:', all_interaction_sessions)
        
    ltm_pg_repo = LongTermMemoryPGRepo(client)
    compressed_sessions = await ltm_pg_repo.get_all_active_session_ids()
    print('compressed_sessions:', compressed_sessions)
    
    today = datetime.now().strftime("%Y%m%d")
    print('today:', today)
    
    uncompressed_ids = []
    for sid in all_interaction_sessions:
        if sid == today:
            continue
        if sid not in compressed_sessions:
            uncompressed_ids.append(sid)
            
    print('uncompressed_ids:', uncompressed_ids)

if __name__ == "__main__":
    asyncio.run(main())
