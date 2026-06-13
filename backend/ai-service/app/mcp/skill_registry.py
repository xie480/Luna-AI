"""
MCP Skill 注册中心。

做什么：管理 MCP Skill 的注册、展开、检索功能。Skill 作为能力指针，
        包含 Tool、Resource 和 Prompt 三要素。Agent 1 在初筛阶段
        仅操作 Skill 级别的元数据，Agent 2 才展开具体内容。
为什么这样做：将 Skill 注册与三阶段 Agent 流程解耦。SkillRegistry
            作为 PG 数据的只读缓存，通过 SQLAlchemy ORM 加载数据。
边界条件：
    - 启动时从 PG 加载所有已注册 Skill。
    - 同一 skill name 不可重复注册。
    - 禁用的 Skill 不会被 Agent 1 召回。
"""

from __future__ import annotations

from typing import Any

from app.logger import logger
from app.utils.snowflake import generate_string_id


class SkillMetadata:
    """Skill 元数据（未展开状态，供 Agent 1 使用）。

    做什么：包含 Skill 的名称、描述和核心能力说明。
            不包含 Tool/Resource/Prompt 的具体内容。
    为什么这样做：Agent 1 在初筛阶段只需要知道 Skill 的
                能力范围和适用场景，不需要加载具体工具。
    """

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str,
        enabled: bool = True,
        version: str = "1.0.0",
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.enabled = enabled
        self.version = version

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，供 Agent 1 Prompt 注入。"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }


class SkillDetail:
    """Skill 完整展开信息（供 Agent 2 使用）。

    做什么：包含 Skill 的所有 Tool 简介、Resource 简介和 Prompt 模板。
            Agent 2 加载阶段使用此信息进行工具和资源的选拔规划。
    为什么这样做：将 Skill 的完整展开信息与元数据分离，避免
                Agent 1 收到过多冗余信息。
    """

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str,
        tools: list[dict[str, Any]],
        resources: list[dict[str, Any]],
        prompts: dict[str, Any],
        version: str = "1.0.0",
        memory_schema: dict[str, Any] | None = None,
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.description = description
        # tools 列表包含轻量元数据（name, description, core_purpose），不含 parameters_schema
        self.tools = tools
        # resources 列表包含资源元数据（name, resource_type, uri, description）
        self.resources = resources
        # prompts 字典包含三个阶段的提示词模板
        self.prompts = prompts
        self.version = version
        # 专属技能的动态多轮记忆上下文 Schema
        self.memory_schema = memory_schema


class SkillRegistry:
    """MCP Skill 注册中心（单例）。"""

    _instance: SkillRegistry | None = None
    _skills: dict[str, SkillDetail] = {}

    def __new__(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._skills = {}
        return cls._instance

    # ---- PG 加载 ----

    async def load_from_pg(self, pg_session: Any) -> None:
        """从 PostgreSQL 加载所有 Skill 到内存缓存。

        做什么：通过 SQLAlchemy ORM 查询 skills 表及关联的
                tools（mcp_tool_registrations）、resources、prompts 表。
        为什么这样做：启动时将 PG 数据加载到内存，避免运行时频繁查表。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
        边界条件：PG 不可用时，缓存为空列表。
                  某个 Skill 数据不完整时，跳过该 Skill。
        """
        from sqlalchemy import select

        from app.repository.models import (
            MCPToolRegistration,
        )
        from app.repository.models import (
            Prompt as PromptModel,
        )
        from app.repository.models import (
            Resource as ResourceModel,
        )
        from app.repository.models import Skill as SkillModel

        try:
            # 查询所有启用的 Skill
            result = await pg_session.execute(
                select(SkillModel).where(SkillModel.enabled == True)  # noqa: E712
            )
            skill_rows = result.scalars().all()

            for skill_row in skill_rows:
                # 查询关联的工具（简介信息，不含 parameters_schema）
                tools_result = await pg_session.execute(
                    select(MCPToolRegistration).where(
                        MCPToolRegistration.skill_id == skill_row.id,
                        MCPToolRegistration.enabled == True,  # noqa: E712
                    )
                )
                tool_rows = tools_result.scalars().all()
                tools = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "core_purpose": t.core_purpose,
                        "final_deliverable": t.final_deliverable,
                        "risk_level": t.risk_level,
                        "category": t.category,
                        "tags": t.tags,
                    }
                    for t in tool_rows
                ]

                # 查询关联的资源
                resources_result = await pg_session.execute(
                    select(ResourceModel).where(ResourceModel.skill_id == skill_row.id)
                )
                resource_rows = resources_result.scalars().all()
                resources = [
                    {
                        "id": r.id,
                        "name": r.name,
                        "resource_type": r.resource_type,
                        "uri": r.uri,
                        "description": r.description,
                        "mime_type": r.mime_type,
                        "auto_load": r.auto_load,
                    }
                    for r in resource_rows
                ]

                # 查询关联的 Prompt
                prompts_result = await pg_session.execute(
                    select(PromptModel).where(
                        PromptModel.skill_id == skill_row.id,
                        PromptModel.status == "published",
                    )
                )
                prompt_rows = prompts_result.scalars().all()
                prompts_by_phase: dict[str, dict[str, str]] = {}
                for p in prompt_rows:
                    prompts_by_phase[p.phase] = {
                        "content_path": p.content_path,
                        "variables": p.variables,
                    }

                # 提取 memory_schema 字段（从 metadata_ 中提取，如果在注册时预留了该字段）
                memory_schema = skill_row.metadata_.get("memory_schema") if skill_row.metadata_ else None

                # 构建 SkillDetail
                detail = SkillDetail(
                    skill_id=skill_row.id,
                    name=skill_row.name,
                    description=skill_row.description,
                    tools=tools,
                    resources=resources,
                    prompts=prompts_by_phase,
                    version=skill_row.version,
                    memory_schema=memory_schema,
                )
                self._skills[skill_row.id] = detail

            logger.info(f"MCP Skill 从 PG 加载完成 count={len(skill_rows)}")

        except Exception as exc:
            logger.error(f"MCP Skill 从 PG 加载失败 error={exc!s}")

    # ---- 查询 ----

    def list_skill_metadata(self) -> list[dict[str, Any]]:
        """列出所有启用的 Skill 元数据（未展开状态）。

        做什么：返回所有 Skill 的轻量元数据，供 Agent 1 初筛使用。
                不包含 Tool/Resource 的具体内容。
        返回:
            list[dict]: 每个 dict 包含 skill_id, name, description, version。
        """
        result: list[dict[str, Any]] = []
        for skill_id, detail in self._skills.items():
            result.append({
                "skill_id": skill_id,
                "name": detail.name,
                "description": detail.description,
                "version": detail.version,
            })
        return result

    def get_skill_detail(self, skill_id: str) -> SkillDetail | None:
        """获取指定 Skill 的完整展开信息。

        做什么：供 Agent 2 在加载阶段使用，获取 Skill 的
                tools、resources、prompts 完整信息。
        参数:
            skill_id: 技能 ID。
        返回:
            SkillDetail 或 None（不存在时）。
        """
        return self._skills.get(skill_id)

    def get_skill_id_by_name(self, name: str) -> str | None:
        """通过名称查询 Skill ID。

        做什么：供 Agent 1 输出 SkillChainPlan 后校验使用。
        参数:
            name: 技能名称。
        返回:
            str 或 None（不存在时）。
        """
        for skill_id, detail in self._skills.items():
            if detail.name == name:
                return skill_id
        return None

    # ---- 管理接口 ----

    async def create_skill(
        self,
        pg_session: Any,
        name: str,
        description: str,
        metadata: dict[str, Any] | None = None,
        version: str = "1.0.0",
    ) -> str:
        """创建新的 Skill（持久化到 PG 并同步缓存）。

        做什么：在 skills 表中插入一条记录，
                同时将 SkillDetail 缓存到内存。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
            name: 技能名称（唯一）。
            description: 技能描述。
            metadata: 扩展元数据，可选。
            version: 版本号，默认 1.0.0。
        返回:
            str: 新创建的 Skill ID。
        抛出:
            ValueError: name 已存在时抛出。
        """
        from app.repository.models import Skill as SkillModel

        # 检查名称是否已存在
        if self.get_skill_id_by_name(name):
            raise ValueError(f"Skill 名称 '{name}' 已存在")

        skill_id = generate_string_id()
        new_skill = SkillModel(
            id=skill_id,
            name=name,
            description=description,
            metadata_=metadata or {},
            version=version,
            enabled=True,
        )
        pg_session.add(new_skill)
        await pg_session.flush()

        # 提取 memory_schema 字段
        memory_schema = metadata.get("memory_schema") if metadata else None

        # 同步缓存
        self._skills[skill_id] = SkillDetail(
            skill_id=skill_id,
            name=name,
            description=description,
            tools=[],
            resources=[],
            prompts={},
            version=version,
            memory_schema=memory_schema,
        )

        logger.info(f"Skill 创建完成 name={name} skill_id={skill_id}")
        return skill_id

    async def delete_skill(self, pg_session: Any, skill_id: str) -> None:
        """删除指定 Skill（级联删除关联的 tools/resources/prompts）。

        做什么：删除 skills 表记录（CASCADE 级联删除关联表），
                同时清理内存缓存。
        参数:
            pg_session: SQLAlchemy 异步会话实例。
            skill_id: 要删除的技能 ID。
        抛出:
            KeyError: skill_id 不存在时抛出。
        """
        from sqlalchemy import select

        from app.repository.models import Skill as SkillModel

        if skill_id not in self._skills:
            raise KeyError(f"Skill '{skill_id}' 不存在")

        result = await pg_session.execute(
            select(SkillModel).where(SkillModel.id == skill_id)
        )
        skill_row = result.scalar_one_or_none()
        if skill_row:
            await pg_session.delete(skill_row)

        del self._skills[skill_id]
        logger.info(f"Skill 删除完成 skill_id={skill_id}")
