"""
MCP 工具配置 PG 仓库。

做什么：提供 ToolConfig 表的 PostgreSQL 持久化能力，支持工具配置的
        增删改查和全量加载。ToolConfigManager 启动时调用 load_all()
        加载所有工具配置到内存缓存。
为什么这样做：工具配置与系统环境变量解耦，用户可在前端 Skill 面板中
             通过工具条目旁的"配置"按钮独立设置每个工具的专有参数。
边界条件：
    - tool_name 唯一，一个工具一条配置记录。
    - 仓库不可用时，配置管理器使用空配置列表。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.repository.models import ToolConfig
from app.utils.snowflake import generate_string_id


class ToolConfigPGRepo:
    """MCP 工具配置 PG 仓库。"""

    def __init__(self, session: AsyncSession | None) -> None:
        """
        初始化工具配置 PG 仓库。

        参数:
            session: SQLAlchemy 异步会话实例。为 None 时仓库不可用。
        """
        self._session = session

    @property
    def is_available(self) -> bool:
        """仓库是否可用。"""
        return self._session is not None

    async def load_all(self) -> list[dict[str, Any]]:
        """
        加载所有工具配置。

        做什么：从 tool_configs 表读取所有状态为 ACTIVE 的记录。
        为什么这样做：供 ToolConfigManager 在初始化时从 PG 加载全量数据。
        返回:
            list[dict]: 工具配置列表，每项包含 tool_name、config_data、status。
                        仓库不可用时返回空列表。
        """
        if not self._session:
            return []
        try:
            result = await self._session.execute(
                select(ToolConfig).where(ToolConfig.status == "ACTIVE")
            )
            rows = result.scalars().all()
            configs: list[dict[str, Any]] = []
            for row in rows:
                configs.append({
                    "id": row.id,
                    "tool_name": row.tool_name,
                    "config_data": row.config_data or {},
                    "status": row.status,
                    "description": row.description or "",
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                })
            logger.info(f"工具配置 PG 加载完成 count={len(configs)}")
            return configs
        except Exception as exc:
            logger.warning(f"工具配置 PG 加载失败: {exc}")
            return []

    async def get_by_tool_name(self, tool_name: str) -> dict[str, Any] | None:
        """
        获取指定工具名称的配置。

        做什么：根据工具名称查询配置记录。
        参数:
            tool_name: 工具名称。
        返回:
            dict 或 None（不存在时）。
        """
        if not self._session:
            return None
        try:
            result = await self._session.execute(
                select(ToolConfig).where(
                    ToolConfig.tool_name == tool_name,
                    ToolConfig.status == "ACTIVE",
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "tool_name": row.tool_name,
                "config_data": row.config_data or {},
                "status": row.status,
                "description": row.description or "",
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
        except Exception as exc:
            logger.warning(f"工具配置查询失败 tool_name={tool_name} error={exc}")
            return None

    async def upsert(
        self,
        tool_name: str,
        config_data: dict[str, Any],
        description: str = "",
    ) -> bool:
        """
        保存或更新工具配置（Upsert 语义）。

        做什么：如果 tool_name 已存在则更新 config_data 和 description，
                否则插入新记录。状态自动设为 ACTIVE。
        参数:
            tool_name: 工具名称。
            config_data: 配置键值对。
            description: 配置说明。
        返回:
            bool: 操作成功返回 True。
        """
        if not self._session:
            return False
        try:
            result = await self._session.execute(
                select(ToolConfig).where(ToolConfig.tool_name == tool_name)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.config_data = config_data
                existing.description = description
                existing.status = "ACTIVE"
                existing.updated_at = datetime.now(timezone.utc)
            else:
                new_config = ToolConfig(
                    id=generate_string_id(),
                    tool_name=tool_name,
                    config_data=config_data,
                    description=description,
                    status="ACTIVE",
                )
                self._session.add(new_config)

            await self._session.commit()
            logger.info(f"工具配置保存完成 tool_name={tool_name}")
            return True
        except Exception as exc:
            await self._session.rollback()
            logger.warning(f"工具配置保存失败 tool_name={tool_name} error={exc}")
            return False

    async def delete(self, tool_name: str) -> bool:
        """
        删除指定工具配置（软删除，设置状态为 INACTIVE）。

        参数:
            tool_name: 工具名称。
        返回:
            bool: 操作成功返回 True。
        """
        if not self._session:
            return False
        try:
            result = await self._session.execute(
                select(ToolConfig).where(ToolConfig.tool_name == tool_name)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.status = "INACTIVE"
                existing.updated_at = datetime.now(timezone.utc)
                await self._session.commit()
                logger.info(f"工具配置软删除完成 tool_name={tool_name}")
                return True
            logger.warning(f"工具配置删除失败: {tool_name} 不存在")
            return False
        except Exception as exc:
            await self._session.rollback()
            logger.warning(f"工具配置删除失败 tool_name={tool_name} error={exc}")
            return False
