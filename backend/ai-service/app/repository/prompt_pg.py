"""
Luna AI PostgreSQL 提示词模板存储库

做什么：提供对 prompt_templates 和 prompt_versions 表的访问。
为什么这样做：管理系统提示词模板及其版本。
输入输出：
    - PromptPGRepo: 提示词模板存储库类
边界条件：
    - 支持事务操作
异常行为：
    - 数据库操作失败时抛出异常
"""

from typing import Callable, Coroutine, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.postgres import PostgresClient
from app.repository.models import PromptTemplate, PromptVersion


class PromptPGRepo:
    """提供对 prompt_templates 和 prompt_versions 表的访问"""

    def __init__(self, pg_client: PostgresClient, session: Optional[AsyncSession] = None):
        self.pg_client = pg_client
        self._session = session # 用于事务中传递 session

    async def _get_session(self):
        """获取 session，如果当前在事务中则返回事务 session"""
        if self._session:
            yield self._session
        else:
            async for session in self.pg_client.get_session():
                yield session

    async def list_templates(self) -> List[PromptTemplate]:
        """获取所有模板列表"""
        async for session in self._get_session():
            stmt = select(PromptTemplate)
            result = await session.execute(stmt)
            return list(result.scalars().all())
        return []

    async def get_template(self, id: str) -> Optional[PromptTemplate]:
        """获取模板"""
        async for session in self._get_session():
            stmt = select(PromptTemplate).where(PromptTemplate.id == id)
            result = await session.execute(stmt)
            return result.scalars().first()
        return None

    async def get_template_by_name(self, name: str) -> Optional[PromptTemplate]:
        """获取模板"""
        async for session in self._get_session():
            stmt = select(PromptTemplate).where(PromptTemplate.name == name)
            result = await session.execute(stmt)
            return result.scalars().first()
        return None

    async def get_templates_by_category(self, category: str) -> List[PromptTemplate]:
        """获取指定分类的模板"""
        async for session in self._get_session():
            stmt = select(PromptTemplate).where(PromptTemplate.category == category)
            result = await session.execute(stmt)
            return list(result.scalars().all())
        return []

    async def create_template(self, template: PromptTemplate) -> None:
        """创建模板"""
        async for session in self._get_session():
            session.add(template)
            if not self._session:
                await session.commit()
            return

    async def update_template(self, template: PromptTemplate) -> None:
        """更新模板"""
        async for session in self._get_session():
            session.add(template)
            if not self._session:
                await session.commit()
            return

    async def get_version(self, id: str) -> Optional[PromptVersion]:
        """获取版本"""
        async for session in self._get_session():
            stmt = select(PromptVersion).where(PromptVersion.id == id)
            result = await session.execute(stmt)
            return result.scalars().first()
        return None

    async def get_versions_by_template(self, template_id: str) -> List[PromptVersion]:
        """获取模板的所有版本"""
        async for session in self._get_session():
            stmt = (
                select(PromptVersion)
                .where(PromptVersion.template_id == template_id)
                .order_by(PromptVersion.version_num.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
        return []

    async def create_version(self, version: PromptVersion) -> None:
        """创建版本"""
        async for session in self._get_session():
            session.add(version)
            if not self._session:
                await session.commit()
            return

    async def update_version(self, version: PromptVersion) -> None:
        """更新版本"""
        async for session in self._get_session():
            session.add(version)
            if not self._session:
                await session.commit()
            return

    async def delete_version(self, id: str) -> None:
        """删除版本"""
        async for session in self._get_session():
            version = await session.get(PromptVersion, id)
            if version:
                await session.delete(version)
                if not self._session:
                    await session.commit()
            return

    async def run_in_transaction(self, fn: Callable[['PromptPGRepo'], Coroutine]) -> None:
        """在事务中执行操作"""
        async for session in self.pg_client.get_session():
            async with session.begin():
                tx_repo = PromptPGRepo(self.pg_client, session=session)
                await fn(tx_repo)
            return
