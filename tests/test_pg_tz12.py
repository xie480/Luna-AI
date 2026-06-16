import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE column_name IN ('created_at', 'updated_at')"))
        for row in res.mappings():
            if row['data_type'] != 'timestamp with time zone':
                print(f"Non-TZ: {row['table_name']}.{row['column_name']} = {row['data_type']}")
        print("Done")
    await engine.dispose()

asyncio.run(main())