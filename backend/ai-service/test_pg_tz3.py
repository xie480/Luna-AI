import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'interactions' AND column_name = 'created_at'"))
        col_type = res.mappings().first()
        if col_type:
            print(f"interactions.created_at type: {col_type['data_type']}")
        
    await engine.dispose()

asyncio.run(main())