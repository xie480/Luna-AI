import asyncio
import asyncpg

async def main():
    try:
        # Based on .env file
        conn = await asyncpg.connect(
            host='192.168.100.128',
            port=5432,
            user='yilena',
            password='XUWENBO219382',
            database='luna_ai'
        )
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    print("Connected to DB.")
    # Try dropping as a constraint
    try:
        await conn.execute('ALTER TABLE prompts DROP CONSTRAINT IF EXISTS idx_prompts_skill_phase_version CASCADE;')
        print("Successfully dropped constraint 'idx_prompts_skill_phase_version' (if it existed as constraint).")
    except Exception as e:
        print(f"Failed to drop constraint: {e}")
        
    # Try dropping as an index
    try:
        await conn.execute('DROP INDEX IF EXISTS idx_prompts_skill_phase_version CASCADE;')
        print("Successfully dropped index 'idx_prompts_skill_phase_version' (if it existed as index).")
    except Exception as e:
        print(f"Failed to drop index: {e}")
        
    result = await conn.fetch("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'prompts'::regclass;
    """)
    print("Current constraints on 'prompts':", [r['conname'] for r in result])
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
