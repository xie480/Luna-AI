import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with AsyncSession(engine) as session:
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content) VALUES ('test_id_1', 'sess_1', 'msg_1', 'u', 'a') ON CONFLICT DO NOTHING"))
        await session.commit()
        
        res = await session.execute(text("SELECT created_at FROM interactions WHERE id='test_id_1'"))
        row = res.mappings().first()
        if row:
            dt = row['created_at']
            print(f"created_at from DB: {repr(dt)}, tzinfo: {dt.tzinfo}")
            print(f"isoformat: {dt.isoformat()}")
        
    await engine.dispose()

asyncio.run(main())