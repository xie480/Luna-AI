"""
Luna AI API 配置预设存储库

做什么：提供对 api_config_presets 表的访问。
为什么这样做：管理不同规格（大、中、小）模型的 API 配置预设。
输入输出：
    - ConfigPresetPGRepo: API 配置预设存储库类
边界条件：
    - 只有一个预设可以处于激活状态
异常行为：
    - 数据库操作失败时抛出异常
"""

from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgres import PostgresClient
from app.repository.models import ApiConfigPreset


class ConfigPresetPGRepo:
    """提供对 api_config_presets 表的访问"""

    def __init__(self, pg_client: PostgresClient):
        self.pg_client = pg_client

    async def get_all(self) -> List[ApiConfigPreset]:
        """获取所有预设"""
        async with self.pg_client.session_factory() as session:
            stmt = select(ApiConfigPreset).order_by(ApiConfigPreset.created_at.desc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_by_id(self, id: str) -> Optional[ApiConfigPreset]:
        """根据 ID 获取预设"""
        async with self.pg_client.session_factory() as session:
            stmt = select(ApiConfigPreset).where(ApiConfigPreset.id == id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_active(self) -> Optional[ApiConfigPreset]:
        """获取当前激活的预设"""
        async with self.pg_client.session_factory() as session:
            stmt = select(ApiConfigPreset).where(ApiConfigPreset.is_active == True)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def save(self, preset: ApiConfigPreset) -> None:
        """保存或更新预设"""
        async with self.pg_client.session_factory() as session:
            # 使用 merge 而非 add：当主键已存在时执行 UPDATE，否则执行 INSERT
            await session.merge(preset)
            await session.commit()

    async def delete(self, id: str) -> None:
        """删除预设"""
        async with self.pg_client.session_factory() as session:
            preset = await session.get(ApiConfigPreset, id)
            if preset:
                await session.delete(preset)
                await session.commit()

    async def set_active(self, id: str) -> None:
        """设置激活的预设，并将其他预设设为非激活"""
        async with self.pg_client.session_factory() as session:
            # 1. 将所有预设设为非激活
            stmt1 = update(ApiConfigPreset).values(is_active=False)
            await session.execute(stmt1)

            # 2. 将指定预设设为激活
            stmt2 = update(ApiConfigPreset).where(ApiConfigPreset.id == id).values(is_active=True)
            await session.execute(stmt2)

            await session.commit()
