import asyncio
import sys
import os
import io

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend', 'ai-service')))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    engine = create_async_engine(settings.postgres_conn_str)
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT chunk_id, content_text FROM rag_chunks LIMIT 1"))
            row = result.first()
            
            if row:
                chunk_id = row[0]
                content = row[1]
                
                print("--- Unicode Codepoints Analysis ---")
                print(f"Original Text (first 50 chars): {content[:50]}")
                print("\nCodepoints:")
                for char in content[:50]:
                    print(f"Char: {char} | Unicode: U+{ord(char):04X} | Name: {char.encode('unicode_escape').decode('ascii')}")
                    
                print("\nCan it be encoded in GBK (Windows Console)?")
                try:
                    content[:50].encode('gbk')
                    print("Yes, full support.")
                except UnicodeEncodeError as e:
                    print(f"NO! Fails at character: {content[:50][e.start]} (U+{ord(content[:50][e.start]):04X})")
                    print("When printed to a Windows console (GBK), this character will become a '?'")
                    print(f"Example of GBK replacement: {content[:50].encode('gbk', errors='replace').decode('gbk')}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
