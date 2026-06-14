import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE data_type LIKE '%timestamp%'"))
        for row in res.mappings():
            print(f"{row['table_name']}.{row['column_name']} = {row['data_type']}")
        print("Done")
    await engine.dispose()

asyncio.run(main())