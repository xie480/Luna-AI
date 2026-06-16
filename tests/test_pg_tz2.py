import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    print(f"Connecting to {conn_str}")
    engine = create_async_engine(conn_str)
    
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT now()"))
        dt = res.scalar()
        print(f"now() from DB: {repr(dt)}, tzinfo: {dt.tzinfo}")
        
    await engine.dispose()

asyncio.run(main())