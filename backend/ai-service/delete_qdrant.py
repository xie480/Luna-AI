import asyncio
from qdrant_client import AsyncQdrantClient

async def main():
    client = AsyncQdrantClient(url='http://192.168.100.128:6333')
    try:
        await client.delete_collection('luna_long_term_memories')
        print('Collection deleted successfully')
    except Exception as e:
        print(f'Error deleting collection: {e}')

if __name__ == "__main__":
    asyncio.run(main())
