import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with AsyncSession(engine) as session:
        # naive local datetime
        dt1 = datetime.utcnow()
        dt2 = datetime.now()
        dt3 = datetime.now(timezone.utc)
        
        print(f"utcnow (naive): {repr(dt1)}")
        print(f"now (naive): {repr(dt2)}")
        print(f"now (aware UTC): {repr(dt3)}")
        
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content, created_at) VALUES ('test_dt1', 'sess', 'msg_dt1', 'u', 'a', :dt) ON CONFLICT (id) DO UPDATE SET created_at = :dt"), {"dt": dt1})
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content, created_at) VALUES ('test_dt2', 'sess', 'msg_dt2', 'u', 'a', :dt) ON CONFLICT (id) DO UPDATE SET created_at = :dt"), {"dt": dt2})
        await session.execute(text("INSERT INTO interactions (id, session_id, message_id, user_content, assistant_content, created_at) VALUES ('test_dt3', 'sess', 'msg_dt3', 'u', 'a', :dt) ON CONFLICT (id) DO UPDATE SET created_at = :dt"), {"dt": dt3})
        await session.commit()
        
        for name, _id in [("utcnow naive", "test_dt1"), ("now naive", "test_dt2"), ("now aware UTC", "test_dt3")]:
            res = await session.execute(text(f"SELECT created_at FROM interactions WHERE id='{_id}'"))
            row = res.mappings().first()
            if row:
                print(f"{name} retrieved: {repr(row['created_at'])}")
        
    await engine.dispose()

asyncio.run(main())