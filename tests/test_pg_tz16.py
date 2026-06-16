import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT created_at FROM interactions LIMIT 1"))
        row = res.mappings().first()
        if row:
            dt = row['created_at']
            print(f"Original from DB: {repr(dt)}")
            print(f"isoformat: {dt.isoformat()}")
            
            # Let's see if we convert it to local timezone
            local_tz = ZoneInfo("Asia/Shanghai")
            dt_local = dt.astimezone(local_tz)
            print(f"Converted to local: {repr(dt_local)}")
            print(f"isoformat (local): {dt_local.isoformat()}")
            
        else:
            print("No data")
        
    await engine.dispose()

asyncio.run(main())