import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with AsyncSession(engine) as session:
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content) VALUES ('test_dt4', 'sess', 'msg_dt4', 'u', 'a') ON CONFLICT (id) DO NOTHING"))
        await session.commit()
        
        res = await session.execute(text("SELECT created_at FROM interactions WHERE id='test_dt4'"))
        row = res.mappings().first()
        if row:
            print(f"func.now() retrieved: {repr(row['created_at'])}")
            print(f"isoformat: {row['created_at'].isoformat()}")
        
    await engine.dispose()

asyncio.run(main())