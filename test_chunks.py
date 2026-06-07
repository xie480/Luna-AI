import asyncio
import sys
import os
import io

# 设置标准输出支持 UTF-8 (应对 Windows 终端)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加包路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend', 'ai-service')))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config.settings import settings

async def main():
    print("Testing Postgres connection to: " + settings.postgres_conn_str.replace(settings.db_password, '***'))
    engine = create_async_engine(settings.postgres_conn_str)
    
    try:
        async with engine.connect() as conn:
            # 查询 rag_chunks 表中的正文
            result = await conn.execute(text("SELECT chunk_id, content_text FROM rag_chunks LIMIT 10"))
            rows = result.all()
            
            print(f"\n找到 {len(rows)} 条 chunk 记录。")
            
            for row in rows:
                chunk_id = row[0]
                content = row[1]
                
                print(f"\n--- Chunk ID: {chunk_id} ---")
                
                # 检查是否存在不可打印的字符或问号 (特别是 \ufffd 或 '?' 的聚集)
                if '?' in content:
                    print(f"[警告] 文本中包含问号 ({content.count('?')}个)")
                if '\ufffd' in content:
                    print(f"[警告] 文本中包含替换字符 \ufffd ({content.count(chr(0xfffd))}个)")
                    
                # 打印前 200 个字符进行预览
                preview = content[:200].replace('\n', ' ')
                print(f"内容预览: {preview}")
                
    except Exception as e:
        print(f"执行失败: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
