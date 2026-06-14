import asyncio
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
            print(f"interactions.created_at: {repr(dt)}, tzinfo: {dt.tzinfo}")
            print(f"isoformat: {dt.isoformat()}")
        else:
            print("No data in interactions")
        
    await engine.dispose()

asyncio.run(main())