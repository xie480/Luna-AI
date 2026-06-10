"""
MCP 工具注册 PG 仓库。

做什么：提供 MCP 工具注册信息的 PostgreSQL 持久化能力，支持工具 Schema 的
        增删改查、启用/禁用状态管理和全量加载。MCPToolRegistry 启动时调用
        load_all() 加载所有已注册的工具。
为什么这样做：Phase 12 要求工具注册必须落库 PG，确保进程重启后注册信息不丢失。
             PG 作为工具注册的 SSOT（Single Source of Truth），内存中的 Registry
             是 PG 数据的只读缓存。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.logger import logger
from app.repository.models import MCPToolRegistration
from app.utils.snowflake import generate_string_id


class MCPToolPGRepo:
    """MCP 工具注册 PG 仓库。"""

    def __init__(self, session: AsyncSession | None) -> None:
        """
        初始化 MCP 工具 PG 仓库。

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
        加载所有已注册工具的完整元数据。

        做什么：从 mcp_tool_registrations 表读取所有记录，返回完整的工具元数据字典列表。
        为什么这样做：供 MCPToolRegistry 在初始化时从 PG 加载全量数据重建内存索引。
        返回:
            list[dict]: 工具元数据列表，每项包含所有数据库字段。
                        仓库不可用时返回空列表。
        """
        if not self._session:
            return []
        try:
            result = await self._session.execute(
                select(MCPToolRegistration).order_by(MCPToolRegistration.created_at)
            )
            rows = result.scalars().all()
            tools: list[dict[str, Any]] = []
            for row in rows:
                tools.append({
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "parameters_schema": row.parameters_schema or {},
                    "risk_level": row.risk_level,
                    "enabled": row.enabled,
                    "tags": row.tags or [],
                    "category": row.category or "",
                    "use_case_examples": row.use_case_examples or [],
                    "core_purpose": row.core_purpose or "",
                    "final_deliverable": row.final_deliverable or "",
                })
            logger.info(f"MCP 工具 PG 加载完成 count={len(tools)}")
            return tools
        except Exception as exc:
            logger.warning(f"MCP 工具 PG 加载失败: {exc}")
            return []

    async def save(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        risk_level: str,
        enabled: bool,
        tags: list[str],
        category: str,
        use_case_examples: list[str],
        core_purpose: str,
        final_deliverable: str,
    ) -> bool:
        """
        保存工具注册信息到 PG（插入或更新）。

        做什么：如果 name 已存在则更新记录，否则插入新记录。
        为什么这样做：工具注册可以是新增或修改（如更新 use_case_examples），
                      upsert 语义避免调用方区分 insert/update。
        返回:
            bool: 保存成功返回 True，失败返回 False。
        """
        if not self._session:
            return False
        try:
            # 查询是否已存在
            result = await self._session.execute(
                select(MCPToolRegistration).where(MCPToolRegistration.name == name)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # 更新现有记录
                existing.description = description
                existing.parameters_schema = parameters_schema
                existing.risk_level = risk_level
                existing.enabled = enabled
                existing.tags = tags
                existing.category = category
                existing.use_case_examples = use_case_examples
                existing.core_purpose = core_purpose
                existing.final_deliverable = final_deliverable
                existing.updated_at = datetime.now(timezone.utc)
            else:
                # 插入新记录
                new_tool = MCPToolRegistration(
                    id=generate_string_id(),
                    name=name,
                    description=description,
                    parameters_schema=parameters_schema,
                    risk_level=risk_level,
                    enabled=enabled,
                    tags=tags,
                    category=category,
                    use_case_examples=use_case_examples,
                    core_purpose=core_purpose,
                    final_deliverable=final_deliverable,
                )
                self._session.add(new_tool)

            await self._session.commit()
            logger.info(f"MCP 工具 PG 保存完成 name={name}")
            return True
        except Exception as exc:
            await self._session.rollback()
            logger.warning(f"MCP 工具 PG 保存失败 name={name} error={exc}")
            return False

    async def set_enabled(self, name: str, enabled: bool) -> bool:
        """
        设置工具的启用/禁用状态。

        参数:
            name: 工具名称。
            enabled: True 为启用，False 为禁用。
        返回:
            bool: 操作成功返回 True，失败返回 False。
        """
        if not self._session:
            return False
        try:
            await self._session.execute(
                update(MCPToolRegistration)
                .where(MCPToolRegistration.name == name)
                .values(enabled=enabled, updated_at=datetime.now(timezone.utc))
            )
            await self._session.commit()
            logger.info(f"MCP 工具状态更新 name={name} enabled={enabled}")
            return True
        except Exception as exc:
            await self._session.rollback()
            logger.warning(f"MCP 工具状态更新失败 name={name} error={exc}")
            return False

    async def delete(self, name: str) -> bool:
        """
        从 PG 中删除指定工具注册信息。

        参数:
            name: 要删除的工具名称。
        返回:
            bool: 删除成功返回 True，失败返回 False。
        """
        if not self._session:
            return False
        try:
            result = await self._session.execute(
                select(MCPToolRegistration).where(MCPToolRegistration.name == name)
            )
            existing = result.scalar_one_or_none()
            if existing:
                await self._session.delete(existing)
                await self._session.commit()
                logger.info(f"MCP 工具 PG 删除完成 name={name}")
                return True
            logger.warning(f"MCP 工具 PG 删除失败: {name} 不存在")
            return False
        except Exception as exc:
            await self._session.rollback()
            logger.warning(f"MCP 工具 PG 删除失败 name={name} error={exc}")
            return False
