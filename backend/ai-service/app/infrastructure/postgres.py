"""
Luna AI PostgreSQL 客户端模块

做什么：封装 SQLAlchemy 异步引擎，提供数据库连接和会话管理。
为什么这样做：作为配置、记忆、状态持久化存储的基础设施。
输入输出：
    - PostgresClient: PostgreSQL 客户端类
边界条件：
    - 禁用默认事务，提升性能
    - 配置连接池参数
异常行为：
    - 连接失败时抛出异常
"""

import asyncio
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.logger import logger


class PostgresClient:
    """封装 PostgreSQL 客户端连接"""

    def __init__(self, conn_str: str):
        """
        创建一个新的 PostgresClient 实例
        :param conn_str: PostgreSQL 连接字符串，格式为 postgresql+asyncpg://user:password@host:port/database
        """
        # 简单的密码隐藏逻辑，用于日志输出
        masked_conn_str = self._mask_password(conn_str)

        try:
            # 配置 SQLAlchemy 异步引擎
            self.engine: AsyncEngine = create_async_engine(
                conn_str,
                poolclass=AsyncAdaptedQueuePool,
                pool_size=100,          # 最大打开连接数
                max_overflow=10,        # 超过 pool_size 后最多可以创建的连接数
                pool_recycle=3600,      # 连接最大存活时间 (1小时)
                pool_pre_ping=True,     # 每次从池中获取连接时测试连接是否可用
                echo=False,             # 是否打印 SQL 语句
            )

            # 创建异步会话工厂
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False, # 提交后不使对象过期
                autocommit=False,
                autoflush=False,
            )

            logger.info(f"PostgreSQL 引擎初始化成功: {masked_conn_str}")
        except Exception as e:
            logger.error(f"PostgreSQL 引擎初始化失败: {masked_conn_str}, 错误: {e}")
            raise

    async def close(self) -> None:
        """关闭 PostgreSQL 连接"""
        if hasattr(self, 'engine') and self.engine is not None:
            await self.engine.dispose()
            logger.info("PostgreSQL 连接已关闭")

    async def ping(self) -> None:
        """测试 PostgreSQL 连接是否可用"""
        async with self.engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))

    async def is_healthy(self) -> bool:
        """检查 PostgreSQL 连接健康状态"""
        try:
            # 使用 asyncio.wait_for 设置超时时间
            await asyncio.wait_for(self.ping(), timeout=2.0)
            return True
        except Exception:
            return False

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取异步会话，用于依赖注入"""
        session = self.session_factory()
        try:
            yield session
        finally:
            await session.close()
            
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取异步会话，用于上下文管理器"""
        session = self.session_factory()
        try:
            yield session
        finally:
            await session.close()

    def _mask_password(self, conn_str: str) -> str:
        """隐藏连接字符串中的密码"""
        if "://" not in conn_str or "@" not in conn_str:
            return conn_str
        start_idx = conn_str.find("://") + 3
        at_idx = conn_str.find("@")
        credentials = conn_str[start_idx:at_idx]
        if ":" not in credentials:
            return conn_str
        user = credentials.split(":", 1)[0]
        return conn_str[:start_idx] + f"{user}:[REDACTED]" + conn_str[at_idx:]
