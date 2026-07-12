import asyncio
from app.mcp.executor import execute_tool
from app.utils.snowflake import generate_string_id
from dotenv import load_dotenv
import os

async def main():
    load_dotenv()
    # 外部工具已经在 discover_sync 里写到了 DB / registry 中
    # youtube 工具的名字一般是 youtube.search_you_tube 或 search_you_tube 等，需要检查
    
    from app.mcp.skill_registry import SkillRegistry
    from app.infrastructure.postgres import PostgresClient
    from app.config.settings import settings
    
    pg_client = PostgresClient(settings.postgres_conn_str)
    skill_registry = SkillRegistry()
    
    async with pg_client.session() as session:
        await skill_registry.load_from_pg(session)
        
    print("Testing execute_tool (fallback)...")
    res = await execute_tool(
        tool_name="youtube.search_you_tube",
        parameters={
            "q": "cats",
            "type": "video",
            "maxResults": 2
        },
        trace_id=generate_string_id(),
        timeout=30.0,
        max_retries=1
    )
    print("Result Success:", res.success)
    print("Result Error:", res.error_message)
    if res.output_text:
        print("Result Text snippet:", res.output_text[:200])

if __name__ == "__main__":
    asyncio.run(main())
