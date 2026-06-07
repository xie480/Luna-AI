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

from contextlib import asynccontextmanager
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

    @asynccontextmanager
    async def _get_session(self):
        """获取 session，如果当前在事务中则返回事务 session"""
        if self._session:
            yield self._session
        else:
            async with self.pg_client.session_factory() as session:
                yield session

    async def list_templates(self) -> List[PromptTemplate]:
        """获取所有模板列表"""
        async with self._get_session() as session:
            stmt = select(PromptTemplate)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_template(self, id: str) -> Optional[PromptTemplate]:
        """获取模板"""
        async with self._get_session() as session:
            stmt = select(PromptTemplate).where(PromptTemplate.id == id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_template_by_name(self, name: str) -> Optional[PromptTemplate]:
        """获取模板"""
        async with self._get_session() as session:
            stmt = select(PromptTemplate).where(PromptTemplate.name == name)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_templates_by_category(self, category: str) -> List[PromptTemplate]:
        """获取指定分类的模板"""
        async with self._get_session() as session:
            stmt = select(PromptTemplate).where(PromptTemplate.category == category)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create_template(self, template: PromptTemplate) -> None:
        """创建模板"""
        async with self._get_session() as session:
            session.add(template)
            if not self._session:
                await session.commit()

    async def update_template(self, template: PromptTemplate) -> None:
        """更新模板"""
        async with self._get_session() as session:
            session.add(template)
            if not self._session:
                await session.commit()

    async def get_version(self, id: str) -> Optional[PromptVersion]:
        """获取版本"""
        async with self._get_session() as session:
            stmt = select(PromptVersion).where(PromptVersion.id == id)
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_versions_by_template(self, template_id: str) -> List[PromptVersion]:
        """获取模板的所有版本"""
        async with self._get_session() as session:
            stmt = (
                select(PromptVersion)
                .where(PromptVersion.template_id == template_id)
                .order_by(PromptVersion.version_num.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def ensure_template_with_version(
        self,
        *,
        name: str,
        category: str,
        slot_position: str,
        content: str,
        variables: list[str],
    ) -> None:
        """
        确保指定 Prompt 模板和已发布版本存在。

        做什么：按 name 查找模板，不存在时创建模板和 published 版本。
        为什么这样做：新增 simple prompt 文件必须在服务启动时进入 PromptManager 可加载的数据源。
        输入输出：输入模板名称、分类、槽位、内容和变量列表，无返回值。
        边界条件：模板已存在时不覆盖，避免破坏用户在 Prompt 管理面板中的自定义版本。
        异常行为：数据库异常向上抛出，由启动流程记录。
        """
        async with self.pg_client.session_factory() as session:
            result = await session.execute(select(PromptTemplate).where(PromptTemplate.name == name))
            existing = result.scalars().first()
            if existing:
                return
            from app.utils.snowflake import generate_string_id

            template = PromptTemplate(
                id=generate_string_id(),
                name=name,
                category=category,
                slot_position=slot_position,
                is_system=True,
            )
            session.add(template)
            await session.flush()
            version = PromptVersion(
                id=generate_string_id(),
                template_id=template.id,
                version_num=1,
                content=content,
                variables=variables,
                status="published",
            )
            session.add(version)
            await session.flush()
            template.active_version_id = version.id
            await session.commit()

    async def create_version(self, version: PromptVersion) -> None:
        """创建版本"""
        async with self._get_session() as session:
            session.add(version)
            if not self._session:
                await session.commit()

    async def update_version(self, version: PromptVersion) -> None:
        """更新版本"""
        async with self._get_session() as session:
            session.add(version)
            if not self._session:
                await session.commit()

    async def delete_version(self, id: str) -> None:
        """删除版本"""
        async with self._get_session() as session:
            version = await session.get(PromptVersion, id)
            if version:
                await session.delete(version)
                if not self._session:
                    await session.commit()

    async def run_in_transaction(self, fn: Callable[['PromptPGRepo'], Coroutine]) -> None:
        """在事务中执行操作"""
        async with self.pg_client.session_factory() as session:
            async with session.begin():
                tx_repo = PromptPGRepo(self.pg_client, session=session)
                await fn(tx_repo)
