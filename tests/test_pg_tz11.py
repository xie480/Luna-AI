import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with AsyncSession(engine) as session:
        # local timezone aware
        now_local = datetime.now(ZoneInfo("Asia/Shanghai"))
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content, created_at) VALUES ('test_id_3', 'sess_3', 'msg_3', 'u', 'a', :dt) ON CONFLICT (id) DO NOTHING"), {"dt": now_local})
        await session.commit()
        
        res = await session.execute(text("SELECT created_at FROM interactions WHERE id='test_id_3'"))
        row = res.mappings().first()
        if row:
            dt = row['created_at']
            print(f"inserted local: {repr(now_local)}")
            print(f"retrieved: {repr(dt)}, isoformat: {dt.isoformat()}")
        
    await engine.dispose()

asyncio.run(main())