"""
Luna AI Qdrant 客户端模块

做什么：封装 Qdrant 向量数据库客户端，提供向量 Upsert、Search、Delete 等操作的统一接口。
为什么这样做：Qdrant 作为本地轻量化向量数据库，用于长期记忆的语义检索。
输入输出：
    - QdrantClientWrapper: Qdrant 客户端类
边界条件：
    - 确保集合存在，不存在则创建
    - 向量维度默认为 1536（OpenAI text-embedding-ada-002 的维度）
异常行为：
    - 连接失败时记录警告，使用降级模式
"""

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List

from app.logger import logger

# 延迟导入 qdrant_client：qdrant_client 是重依赖（含 gRPC 和 HTTP 客户端），
# 不在模块级导入。在 QdrantClientWrapper 的每个方法内部延迟导入，
# 这样即使包未安装或服务不可用，也不会阻断其他模块的导入。

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient  # type: ignore
    from qdrant_client.http import models  # type: ignore

# QdrantCollection 定义 Qdrant 集合常量
# 长期记忆向量集合：存储每日会话摘要的 Embedding，用于语义检索
QDRANT_COLLECTION_LONG_TERM_MEMORIES = "luna_long_term_memories"


class QdrantSearchResult:
    """Qdrant 搜索结果结构"""
    def __init__(self, id: int, score: float, payload: Dict[str, Any]):
        self.id = id
        self.score = score
        self.payload = payload


class UpsertPoint:
    """单个向量点请求"""
    def __init__(self, id: int, vector: List[float], payload: Dict[str, Any]):
        self.id = id
        self.vector = vector
        self.payload = payload


class QdrantClientWrapper:
    """封装 Qdrant 向量数据库客户端"""

    def __init__(self, base_url: str = "http://localhost:6333"):
        """
        创建一个新的 QdrantClient 实例
        :param base_url: Qdrant HTTP API 地址
        """
        self.base_url = base_url
        # 在构造函数中延迟导入，避免未安装时阻断整个模块加载
        try:
            from qdrant_client import AsyncQdrantClient  # type: ignore
            self.client = AsyncQdrantClient(url=base_url, timeout=10.0)
            logger.info(f"Qdrant 客户端初始化: {base_url}")
        except ImportError:
            logger.warning("qdrant_client 包未安装，Qdrant 功能不可用")
            self.client = None

    async def _ensure_client(self) -> None:
        """确保客户端已初始化，否则抛出异常"""
        if self.client is None:
            raise RuntimeError("Qdrant 客户端未初始化，请安装 qdrant_client 包")

    async def ping(self) -> None:
        """测试 Qdrant 连接是否可用"""
        await self._ensure_client()
        # 获取集合列表作为 ping 测试
        await self.client.get_collections()

    async def is_healthy(self) -> bool:
        """检查 Qdrant 连接健康状态"""
        try:
            await asyncio.wait_for(self.ping(), timeout=2.0)
            return True
        except Exception:
            return False

    async def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """
        确保集合存在，不存在则创建
        :param collection_name: 集合名称
        :param vector_size: 向量维度
        """
        await self._ensure_client()
        from qdrant_client.http import models  # type: ignore

        try:
            exists = await self.client.collection_exists(collection_name=collection_name)
            if exists:
                logger.info(f"Qdrant 集合已存在: {collection_name}")
                return

            # 创建集合
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE
                )
            )
            logger.info(f"Qdrant 集合已创建: {collection_name}, vector_size: {vector_size}")
        except Exception as e:
            logger.error(f"确保 Qdrant 集合存在失败: {e}")
            raise

    async def upsert(self, collection_name: str, points: List[UpsertPoint]) -> None:
        """
        插入或更新向量点
        :param collection_name: 集合名称
        :param points: 要插入的向量点列表
        """
        await self._ensure_client()
        from qdrant_client.http import models  # type: ignore

        if not points:
            return

        try:
            qdrant_points = [
                models.PointStruct(
                    id=p.id,
                    vector=p.vector,
                    payload=p.payload
                )
                for p in points
            ]
            
            await self.client.upsert(
                collection_name=collection_name,
                points=qdrant_points
            )
            logger.info(f"Qdrant Upsert 成功 [collection={collection_name}], count: {len(points)}")
        except Exception as e:
            logger.error(f"Qdrant Upsert 失败 [collection={collection_name}]: {e}")
            raise

    async def search_groups(
        self,
        collection_name: str,
        query_vector: List[float],
        group_by: str,
        limit: int,
        group_size: int = 1
    ) -> List[Any]:
        """
        执行向量相似度分组搜索
        :param collection_name: 集合名称
        :param query_vector: 查询向量
        :param group_by: 分组字段名（必须在 payload 中）
        :param limit: 返回的分组数量
        :param group_size: 每个分组保留的结果数量
        :return: 分组结果列表
        """
        await self._ensure_client()
        
        try:
            results = await self.client.search_groups(
                collection_name=collection_name,
                query_vector=query_vector,
                group_by=group_by,
                limit=limit,
                group_size=group_size,
                with_payload=True
            )
            
            logger.info(f"Qdrant SearchGroups 完成 [collection={collection_name}], groups: {len(results.groups)}")
            return results.groups
        except Exception as e:
            logger.error(f"Qdrant SearchGroups 失败 [collection={collection_name}]: {e}")
            raise

    async def search(self, collection_name: str, vector: List[float], top_k: int) -> List[QdrantSearchResult]:
        """
        执行向量相似度搜索
        :param collection_name: 集合名称
        :param vector: 查询向量
        :param top_k: 返回 Top-K 结果
        :return: 搜索结果列表
        """
        await self._ensure_client()

        try:
            results = await self.client.query_points(
                collection_name=collection_name,
                query=vector,
                limit=top_k,
                with_payload=True
            )
            
            search_results = [
                QdrantSearchResult(
                    id=res.id,
                    score=res.score,
                    payload=res.payload or {}
                )
                for res in results.points
            ]
            
            logger.info(f"Qdrant Search 完成 [collection={collection_name}], hits: {len(search_results)}")
            return search_results
        except Exception as e:
            logger.error(f"Qdrant Search 失败 [collection={collection_name}]: {e}")
            raise

    async def delete_points(self, collection_name: str, ids: List[int]) -> None:
        """
        删除指定 ID 的向量点
        :param collection_name: 集合名称
        :param ids: 要删除的点 ID 列表
        """
        await self._ensure_client()
        from qdrant_client.http import models  # type: ignore

        if not ids:
            return

        try:
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(
                    points=ids
                )
            )
            logger.info(f"Qdrant DeletePoints 完成 [collection={collection_name}], count: {len(ids)}")
        except Exception as e:
            logger.error(f"Qdrant DeletePoints 失败 [collection={collection_name}]: {e}")
            raise