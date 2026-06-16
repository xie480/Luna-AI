import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres@localhost:5432/luna')
    async with engine.begin() as conn:
        print("Connected to DB.")
        # Try dropping as a constraint
        try:
            await conn.execute(text('ALTER TABLE prompts DROP CONSTRAINT IF EXISTS idx_prompts_skill_phase_version CASCADE;'))
            print("Successfully dropped constraint 'idx_prompts_skill_phase_version' (if it existed as constraint).")
        except Exception as e:
            print(f"Failed to drop constraint: {e}")
            
        # Try dropping as an index
        try:
            await conn.execute(text('DROP INDEX IF EXISTS idx_prompts_skill_phase_version CASCADE;'))
            print("Successfully dropped index 'idx_prompts_skill_phase_version' (if it existed as index).")
        except Exception as e:
            print(f"Failed to drop index: {e}")
            
        # See existing constraints
        result = await conn.execute(text("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'prompts'::regclass;
        """))
        print("Current constraints on 'prompts':", [r[0] for r in result])

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
