import asyncio
import os
from dotenv import load_dotenv

# Ensure we load env to get POSTGRES_URL
load_dotenv()

from app.infrastructure.postgres import PostgresClient
from app.config.settings import settings
from sqlalchemy import text

async def clean():
    pg = PostgresClient(os.environ.get("POSTGRES_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/luna"))
    async with pg.session() as s:
        await s.execute(text("DELETE FROM mcp_server_configs WHERE server_id LIKE 'smithery_%'"))
        await s.execute(text("DELETE FROM mcp_tool_registrations WHERE server_id LIKE 'smithery_%'"))
        await s.commit()
    print('Cleaned legacy toolbox servers')

if __name__ == "__main__":
    asyncio.run(clean())
