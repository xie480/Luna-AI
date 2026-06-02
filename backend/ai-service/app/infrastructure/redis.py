"""
Luna AI Redis 客户端模块

做什么：封装 redis.asyncio 客户端连接。
为什么这样做：用于 DAG 工作流毫秒级状态同步与 Event Bus。
输入输出：
    - RedisClient: Redis 客户端类
边界条件：
    - 支持密码认证
    - 支持指定数据库编号
异常行为：
    - 连接失败时抛出异常
"""

import asyncio
from typing import Optional

import redis.asyncio as redis

from app.logger import logger


class RedisClient:
    """封装 Redis 客户端连接"""

    def __init__(self, addr: str, password: str = "", db: int = 0):
        """
        创建一个新的 RedisClient 实例
        :param addr: Redis 服务器地址，格式为 host:port
        :param password: Redis 密码，本地开发通常为空
        :param db: Redis 数据库编号
        """
        try:
            # 创建 Redis 客户端配置
            # decode_responses=True 使得返回的字符串自动解码为 str 而不是 bytes
            self.client = redis.Redis.from_url(
                f"redis://{addr}/{db}",
                password=password if password else None,
                decode_responses=True
            )
            logger.info(f"Redis 客户端初始化成功: {addr}, db: {db}")
        except Exception as e:
            logger.error(f"Redis 客户端初始化失败: {addr}, 错误: {e}")
            raise

    async def close(self) -> None:
        """关闭 Redis 连接"""
        if hasattr(self, 'client') and self.client is not None:
            await self.client.aclose()
            logger.info("Redis 连接已关闭")

    async def ping(self) -> None:
        """测试 Redis 连接是否可用"""
        await self.client.ping()

    async def is_healthy(self) -> bool:
        """检查 Redis 连接健康状态"""
        try:
            # 使用 asyncio.wait_for 设置超时时间
            await asyncio.wait_for(self.ping(), timeout=2.0)
            return True
        except Exception:
            return False

    def get_client(self) -> redis.Redis:
        """获取原始 Redis 客户端实例"""
        return self.client
