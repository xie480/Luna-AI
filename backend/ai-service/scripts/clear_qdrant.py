import asyncio
import logging
from qdrant_client import AsyncQdrantClient

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 修改为你的 Qdrant 实际地址，如果没有设置密码，使用这个默认值即可
import os
from dotenv import load_dotenv

load_dotenv()
QDRANT_URL = os.getenv("QDRANT_ADDRESS", "http://localhost:6333")
# 确保名称与 constants 中定义的一致
COLLECTION_NAME = "luna_long_term_memories"

async def clear_qdrant_data():
    logger.info(f"正在连接到 Qdrant: {QDRANT_URL}")
    try:
        client = AsyncQdrantClient(url=QDRANT_URL, timeout=10.0)
        
        # 1. 检查 Collection 是否存在
        exists = await client.collection_exists(collection_name=COLLECTION_NAME)
        if not exists:
            logger.info(f"Collection '{COLLECTION_NAME}' 不存在，无需清理。")
            return
            
        # 2. 删除整个 Collection
        logger.info(f"正在删除 Collection '{COLLECTION_NAME}' ...")
        await client.delete_collection(collection_name=COLLECTION_NAME)
        logger.info(f"Collection '{COLLECTION_NAME}' 已被成功删除，数据已清空。")
        
        # 注意: 业务代码在下次启动 manager.init() 时会自动调用 ensure_collection 重建该集合
        logger.info("系统在下一次启动时会自动重建该集合。")
        
    except Exception as e:
        logger.error(f"清理 Qdrant 数据时发生错误: {e}")
    finally:
        # 关闭客户端连接 (如果有相应的 close 方法)
        if hasattr(client, 'close'):
             await client.close()

if __name__ == "__main__":
    asyncio.run(clear_qdrant_data())