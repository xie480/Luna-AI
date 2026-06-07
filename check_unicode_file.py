import asyncio
import sys
import os
import io

# 不改变 sys.stdout，直接捕捉异常
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
                
                # 写入到文件，因为控制台可能无法打印
                with open("unicode_test_output.txt", "w", encoding="utf-8") as f:
                    f.write("--- Unicode Codepoints Analysis ---\n")
                    f.write(f"Original Text: {content[:200]}\n\n")
                    f.write("Codepoints:\n")
                    for char in content[:200]:
                        f.write(f"Char: {char} | Unicode: U+{ord(char):04X} | Name: {char.encode('unicode_escape').decode('ascii')}\n")
                        
                    f.write("\nGBK Encode Test:\n")
                    try:
                        content[:200].encode('gbk')
                        f.write("Fully supported by GBK.\n")
                    except UnicodeEncodeError as e:
                        bad_char = content[:200][e.start]
                        f.write(f"FAILS at character: {bad_char} (U+{ord(bad_char):04X})\n")
                        replaced = content[:200].encode('gbk', errors='replace').decode('gbk')
                        f.write(f"What terminal sees: {replaced}\n")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
