import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres@localhost:5432/luna_ai')
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_logs'"))
        columns = [r[0] for r in res]
        print(f"Columns in audit_logs: {columns}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
